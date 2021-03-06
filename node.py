from typing import Iterable, Optional, Union

import torch

from bindsnet.network.nodes import Nodes

class QuintanaExcNodes(Nodes):
    # language=rst
    """
    Layer of leaky integrate-and-fire (LIF) neurons with adaptive thresholds, using current based synapse.
    """

    def __init__(
        self,
        n: Optional[int] = None,
        shape: Optional[Iterable[int]] = None,
        traces: bool = False,
        traces_additive: bool = False,
        tc_trace: Union[float, torch.Tensor] = 20.0,
        trace_scale: Union[float, torch.Tensor] = 1.0,
        sum_input: bool = False,
        rest: Union[float, torch.Tensor] = -65.0,
        reset: Union[float, torch.Tensor] = -65.0,
        thresh: Union[float, torch.Tensor] = -52.0,
        refrac: Union[int, torch.Tensor] = 2,
        tc_decay: Union[float, torch.Tensor] = 100.0,
        theta_plus: Union[float, torch.Tensor] = 0.05,
        tc_theta_decay: Union[float, torch.Tensor] = 2e7,
        R: Union[float, torch.Tensor] = 32,
        tau_inc: Union[float, torch.Tensor] = 10.,
        tau_dec: Union[float, torch.Tensor] = 5.,
        lbound: float = -100.0,
        **kwargs,
    ) -> None:
        # language=rst
        """
        Instantiates a layer of Hao & Huang(2019) excitatory neurons.

        :param n: The number of neurons in the layer.
        :param shape: The dimensionality of the layer.
        :param traces: Whether to record spike traces.
        :param traces_additive: Whether to record spike traces additively.
        :param tc_trace: Time constant of spike trace decay.
        :param trace_scale: Scaling factor for spike trace.
        :param sum_input: Whether to sum all inputs.
        :param rest: Resting membrane voltage.
        :param reset: Post-spike reset voltage.
        :param thresh: Spike threshold voltage.
        :param refrac: Refractory (non-firing) period of the neuron.
        :param tc_decay: Time constant of neuron voltage decay.
        :param theta_plus: Voltage increase of threshold after spiking.
        :param tc_theta_decay: Time constant of adaptive threshold decay.
        :param lbound: Lower bound of the voltage.
        """
        super().__init__(
            n=n,
            shape=shape,
            traces=traces,
            traces_additive=traces_additive,
            tc_trace=tc_trace,
            trace_scale=trace_scale,
            sum_input=sum_input,
        )

        self.register_buffer("rest", torch.tensor(rest))  # Rest voltage.
        self.register_buffer("reset", torch.tensor(reset))  # Post-spike reset voltage.
        self.register_buffer("thresh", torch.tensor(thresh))  # Spike threshold voltage.
        self.register_buffer(
            "refrac", torch.tensor(refrac)
        )  # Post-spike refractory period.
        self.register_buffer(
            "tc_decay", torch.tensor(tc_decay)
        )  # Time constant of neuron voltage decay.
        self.register_buffer(
            "decay", torch.empty_like(self.tc_decay)
        )  # Set in compute_decays.
        self.register_buffer(
            "theta_plus", torch.tensor(theta_plus)
        )  # Constant threshold increase on spike.
        self.register_buffer(
            "tc_theta_decay", torch.tensor(tc_theta_decay)
        )  # Time constant of adaptive threshold decay.
        self.register_buffer(
            "theta_decay", torch.empty_like(self.tc_theta_decay)
        )  # Set in compute_decays.

        self.register_buffer("v", torch.FloatTensor())  # Neuron voltages.
        self.register_buffer("theta", torch.ones(*self.shape) * 20)  # Adaptive thresholds.
        self.register_buffer(
            "refrac_count", torch.FloatTensor()
        )  # Refractory period counters.
        self.register_buffer("I", torch.FloatTensor())
        self.register_buffer("X", torch.FloatTensor())
        self.register_buffer(
            "tau_inc", torch.tensor(tau_inc)
        )
        self.register_buffer(
            "tau_dec", torch.tensor(tau_dec)
        )
        self.register_buffer(
            "I_decay", torch.empty_like(self.tau_dec)
        )
        self.register_buffer(
            "X_decay", torch.empty_like(self.tau_dec)
        )
        self.register_buffer(
            "C", torch.empty_like(self.tau_dec)
        )
        self.register_buffer(
            "R", torch.tensor(R)
        )
        self.lbound = lbound  # Lower bound of voltage.

    def forward(self, x: torch.Tensor) -> None:
        # language=rst
        """
        Runs a single simulation step.

        :param x: Inputs to the layer.
        """
        # Decay voltages and adaptive thresholds.
        self.v += self.decay * (self.rest - self.v + self.R*self.I)
        self.I += self.I_decay * (self.C*self.X - self.I)
        self.X -= self.X_decay * self.X

        if self.learning:
            self.theta -= self.theta_decay * self.theta

        # Integrate inputs.
        x.masked_fill_(self.refrac_count > 0, 0.0) # OPTIM 2
        # Decrement refractory counters.
        self.refrac_count -= self.dt  # OPTIM 1

        self.X += x

        # Check for spiking neurons.
        self.s = self.v >= (self.thresh + self.theta)

        # Refractoriness, voltage reset, and adaptive thresholds.
        self.refrac_count.masked_fill_(self.s, self.refrac)
        self.v.masked_fill_(self.s, self.reset)
        if self.learning:
            scaling_factor = 1#10 / (self.theta - 10).abs()
            self.theta += scaling_factor * self.theta_plus * self.s.float().sum(0)

        # voltage clipping to lowerbound
        if self.lbound is not None:
            self.v.masked_fill_(self.v < self.lbound, self.lbound)

        super().forward(x)

    def reset_state_variables(self) -> None:
        # language=rst
        """
        Resets relevant state variables.
        """
        super().reset_state_variables()
        self.v.fill_(self.rest)  # Neuron voltages.
        self.X.fill_(0.)  # Neuron voltages.
        self.I.fill_(0.)  # Neuron voltages.
        self.refrac_count.zero_()  # Refractory period counters.

    def compute_decays(self, dt) -> None:
        # language=rst
        """
        Sets the relevant decays.
        """
        super().compute_decays(dt=dt)
        self.decay = self.dt/self.tc_decay
        self.theta_decay = self.dt/self.tc_theta_decay
        self.C = (self.tau_dec / self.tau_inc) ** (self.tau_inc / (self.tau_dec - self.tau_inc))
        self.I_decay = self.dt / self.tau_inc
        self.X_decay = self.dt / self.tau_dec

    def set_batch_size(self, batch_size) -> None:
        # language=rst
        """
        Sets mini-batch size. Called when layer is added to a network.

        :param batch_size: Mini-batch size.
        """
        super().set_batch_size(batch_size=batch_size)
        self.X = torch.zeros(batch_size, *self.shape, device=self.X.device)
        self.I = torch.zeros(batch_size, *self.shape, device=self.I.device)
        self.v = self.rest * torch.ones(batch_size, *self.shape, device=self.v.device)
        self.refrac_count = torch.zeros_like(self.v, device=self.refrac_count.device)

class QuintanaSLNodes(Nodes):
    # language=rst
    """
    Layer of supervised learning / supervision layer (SL) neurons
    adapted from Hao & Huang's paper.
    """

    def __init__(
        self,
        n: Optional[int] = None,
        shape: Optional[Iterable[int]] = None,
        traces: bool = False,
        traces_additive: bool = False,
        tc_trace: Union[float, torch.Tensor] = 20.0,
        trace_scale: Union[float, torch.Tensor] = 1.0,
        sum_input: bool = False,
        rest: Union[float, torch.Tensor] = -60.0,
        reset: Union[float, torch.Tensor] = -45.0,
        thresh: Union[float, torch.Tensor] = -40.0,
        tc_decay: Union[float, torch.Tensor] = 10.0,
        R: Union[float, torch.Tensor] = 32,
        tau_inc: Union[float, torch.Tensor] = 10.,
        tau_dec: Union[float, torch.Tensor] = 5.,
        **kwargs,
    ) -> None:
        # language=rst
        """
        Instantiates a layer of Hao & Huang(2019) SL neurons.

        :param n: The number of neurons in the layer.
        :param shape: The dimensionality of the layer.
        :param traces: Whether to record spike traces.
        :param traces_additive: Whether to record spike traces additively.
        :param tc_trace: Time constant of spike trace decay.
        :param trace_scale: Scaling factor for spike trace.
        :param sum_input: Whether to sum all inputs.
        :param rest: Resting membrane voltage.
        :param reset: Post-spike reset voltage.
        :param thresh: Spike threshold voltage.
        :param tc_decay: Time constant of neuron voltage decay.
        """
        super().__init__(
            n=n,
            shape=shape,
            traces=traces,
            traces_additive=traces_additive,
            tc_trace=tc_trace,
            trace_scale=trace_scale,
            sum_input=sum_input,
        )

        self.register_buffer("rest", torch.tensor(rest))  # Rest voltage.
        self.register_buffer("reset", torch.tensor(reset))  # Post-spike reset voltage.
        self.register_buffer("thresh", torch.tensor(thresh))  # Spike threshold voltage.
        self.register_buffer(
            "tc_decay", torch.tensor(tc_decay)
        )  # Time constant of neuron voltage decay.
        self.register_buffer(
            "decay", torch.empty_like(self.tc_decay)
        )  # Set in compute_decays.
        self.register_buffer("I", torch.FloatTensor())
        self.register_buffer("X", torch.FloatTensor())
        self.register_buffer(
            "tau_inc", torch.tensor(tau_inc)
        )
        self.register_buffer(
            "tau_dec", torch.tensor(tau_dec)
        )
        self.register_buffer(
            "I_decay", torch.empty_like(self.tau_dec)
        )
        self.register_buffer(
            "X_decay", torch.empty_like(self.tau_dec)
        )
        self.register_buffer(
            "C", torch.empty_like(self.tau_dec)
        )
        self.register_buffer(
            "R", torch.tensor(R)
        )
        self.register_buffer("v", torch.FloatTensor()) 

    def forward(self, x: torch.Tensor) -> None:
        # language=rst
        """
        Runs a single simulation step.

        :param x: Inputs to the layer.
        """
        if not self.learning:
            # Decay voltages and adaptive thresholds.
            #self.v += self.decay * (self.rest - self.v)

            self.v += self.decay * (self.rest - self.v + self.R*self.I)
            self.I += self.I_decay * (self.C*self.X - self.I)
            self.X -= self.X_decay * self.X


            # Integrate inputs.
            self.X += x

        # Check for spiking neurons.
        self.s = self.v >= self.thresh

        # Voltage reset.
        self.v.masked_fill_(self.s, self.reset)

        super().forward(x)

    def reset_state_variables(self) -> None:
        # language=rst
        """
        Resets relevant state variables.
        """
        super().reset_state_variables()
        self.X.fill_(0.)  # Neuron voltages.
        self.I.fill_(0.)  # Neuron voltages.
        self.v.fill_(self.rest)  # Neuron voltages.

    def compute_decays(self, dt) -> None:
        # language=rst
        """
        Sets the relevant decays.
        """
        super().compute_decays(dt=dt)
        self.decay = self.dt / self.tc_decay
        self.C = (self.tau_dec / self.tau_inc) ** (self.tau_inc / (self.tau_dec - self.tau_inc))
        self.I_decay = self.dt / self.tau_inc
        self.X_decay = self.dt / self.tau_dec

    def set_batch_size(self, batch_size) -> None:
        # language=rst
        """
        Sets mini-batch size. Called when layer is added to a network.

        :param batch_size: Mini-batch size.
        """
        super().set_batch_size(batch_size=batch_size)
        self.X = torch.zeros(batch_size, *self.shape, device=self.X.device)
        self.I = torch.zeros(batch_size, *self.shape, device=self.I.device)
        self.v = self.rest * torch.ones(batch_size, *self.shape, device=self.v.device)
