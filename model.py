from typing import Optional, Union, Sequence, Iterable

import torch

from bindsnet.network import Network
from bindsnet.network.nodes import Input, LIFNodes
from bindsnet.network.topology import Connection

from .node import QuintanaExcNodes, QuintanaSLNodes
from .learning import DA_STDP
from .connection import YewConnection
from .utils import get_network_const, get_lrate

class Quintana2020(Network):
    # language=rst
    """
    Modifies ``HaoAndHuang2019v2`` model by changing the weight normalization between
    hidden layer and SL layer. Originally normalizes weights along post-neurons,
    altered to normalizes weights along pre-neurons for better label assignment
    to hidden layer (excitatory) neurons.
    """

    def __init__(
        self,
        n_inpt: int,
        n_outpt: int,
        n_neurons: int = 100,
        inh: float = 60.0,
        time: int = 350,
        dt: float = 0.5,
        nu: Optional[Union[float, Sequence[float]]] = (1e-4, 1e-2),
        reduction: Optional[callable] = None,
        in_wmin: Optional[float] = 0.0,
        in_wmax: Optional[float] = 1.0,
        out_wmin: Optional[float] = 0.0,
        out_wmax: Optional[float] = 8.0,
        norm_scale: float = 0.1,
        theta_plus: float = 0.05,
        tc_theta_decay: float = 2e7,
        inpt_shape: Optional[Iterable[int]] = None,
        method: bool = False,
    ) -> None:
        # language=rst
        """
        Constructor for class ``HaoAndHuang2019v3``.

        :param n_inpt: Number of input neurons. Matches the 1D size of the input data.
        :param n_neurons: Number of excitatory, inhibitory neurons.
        :param n_outpt: Number of output neurons. Matches the number of
            labels (classes).
        :param inh: Strength of synapse weights from inhibitory to excitatory layer.
        :param time: Length of Poisson spike train per input variable.
        :param dt: Simulation time step.
        :param nu: Single or pair of learning rates for pre- and post-synaptic events,
            respectively.
        :param reduction: Method for reducing parameter updates along the minibatch
            dimension.
        :param in_wmin: Minimum allowed weight on input to excitatory synapses.
        :param in_wmax: Maximum allowed weight on input to excitatory synapses.
        :param out_wmin: Minimum allowed weight on excitatory synapses to output.
        :param out_wmax: Maximum allowed weight on excitatory synapses to output.
        :param norm_scale: Scaling factor of normalization for
            layer connection weights.
        :param theta_plus: On-spike increment of ``HaoExcNodes`` membrane
            threshold potential.
        :param tc_theta_decay: Time constant of ``HaoExcNodes`` threshold
            potential decay.
        :param inpt_shape: The dimensionality of the input layer.
        :param method: Training method. Simultaneous if True, Layer-by-layer if False.
        """
        super().__init__(dt=dt)

        self.n_inpt = n_inpt
        self.n_outpt = n_outpt
        self.inpt_shape = inpt_shape
        self.n_neurons = n_neurons
        self.inh = inh
        self.time = time
        self.dt = dt

        # Training method.
        self.method = "Layer-by-layer" if method else "Simultaneous"

        # Set default value.
        default_value = (theta_plus, tc_theta_decay)

        # Get theta constants based on network size.
        _, tc_theta_decay = get_network_const(self.n_neurons, default_value)

        # Get learning rate based on network size.
        nu_exc, nu_sl = get_lrate(self.n_neurons, (nu, nu))

        # Layers.
        input_layer = Input(
            n=self.n_inpt, shape=self.inpt_shape, traces=True, tc_trace=20.0
        )

        hidden_layer = QuintanaExcNodes(
            n=self.n_neurons,
            traces=True,
            rest=0.0,
            reset=0.0,
            thresh=120.0,
            refrac=2,
            tc_decay=100.0,
            tc_trace=20.0,
            theta_plus=theta_plus,
            tc_theta_decay=tc_theta_decay,
            tau_inc = 10.,
            tau_dec = 5.,
        )

        output_layer = QuintanaSLNodes(
            n=self.n_outpt,
            traces=True,
            rest=0.0,  # Originally -60.0, adjusted for recurrent inhibitory connection.
            reset=0.0,
            thresh=75.0,
            tc_decay=10.0,
            tc_trace=20.0,
            R=32.,
            tau_inc=10.,
            tau_dec=5.
        )

        # Connections.
        w = torch.rand(self.n_inpt, self.n_neurons) * in_wmax
        norm = norm_scale * self.n_inpt * in_wmax  # Set normalization constant.
        input_connection = Connection(
            source=input_layer,
            target=hidden_layer,
            w=w,
            update_rule=DA_STDP,
            nu=nu_exc,
            reduction=reduction,
            wmin=in_wmin,
            wmax=in_wmax,
            norm=norm,
        )

        w = -self.inh * (
            torch.ones(self.n_neurons, self.n_neurons)
            - torch.diag(torch.ones(self.n_neurons))
        )
        recurrent_connection = Connection(
            source=hidden_layer,
            target=hidden_layer,
            w=w,
            wmin=-self.inh,
            wmax=0,
        )

        w = torch.rand(self.n_neurons, self.n_outpt) * out_wmax
        norm = norm_scale * self.n_outpt * out_wmax  # Set normalization constant.
        output_connection = YewConnection(
            source=hidden_layer,
            target=output_layer,
            w=w,
            update_rule=DA_STDP,
            nu=nu_sl,
            reduction=reduction,
            wmin=out_wmin,
            wmax=out_wmax,
            norm=norm,
        )

        # Add to network.
        self.add_layer(input_layer, name="X")
        self.add_layer(hidden_layer, name="Y")
        self.add_layer(output_layer, name="Z")
        self.add_connection(input_connection, source="X", target="Y")
        self.add_connection(recurrent_connection, source="Y", target="Y")
        self.add_connection(output_connection, source="Y", target="Z")
