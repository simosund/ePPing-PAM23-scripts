# Scripts for experiments with ePPing for PAM23
This repository contains scripts used for the experiments in the paper
"Efficient continuous latency monitoring with eBPF" submitted to
PAM 2023.

The shell scripts are used for running the actual experiments, while
the python scripts are used to parse and plot data from the
experiments (the shell scripts call several of the python scripts to
automatically generate the plots).

## How to recreate the plots from the paper
To recreate the figures presented in the paper, one must first
download the raw results available at
[10.5281/zenodo.7555410](https://doi.org/10.5281/zenodo.7555410). Then,
simply follow the instructions provided in the notebook
[PAM_2023_figs.ipynb](PAM_2023_figs.ipynb).

Note that to be able to recreate some of the plots (specifically those
comparing the RTTs computed by tshark, PPing and ePPing), one must
have a slightly modified version of PPing (available at
[10.5281/zenodo.7589243](https://doi.org/10.5281/zenodo.7589243))
installed on the local machine when running the notebook.

## How to repeat the experiments from the paper

### Testbed setup
All the test scripts assume a simple chain topology in the form:

M1 <-> M2 <-> M3

Where M1 and M3 are end hosts, and M2 is a middlebox configured to
forward the traffic between M1 and M3. M1 is assumed to be the sender
and M3 the receiver (M1 will run iperf3 upload flows from M1 to
M3). The scripts fetch necessary information such as which machines to
SSH into, interface names and IP-addresses from the
[experiments.conf](experiments.conf) file. Please make sure the
[experiments.conf](experiments.conf) file contains accurate
information for your testbed (it's pre-filled with example information
from our setup).

The scripts also assume that sar, ss and tc are installed on all
machines, that iperf3 is installed on M1 and M3, and that PPing,
ePPing and tcpdump are installed on M2. Furthermore the scripts assume
that you have setup passwordless SSH access to all machines in the
testbed, as well as passwordless sudo access on M2 (PPing, ePPing and
tcpdump need to be run as sudo).

For all tests, we disabled network offloads on M2. This can be
accomplished by running:
```
sudo ethtool -K <interface> lro off gro off gso off tso off
```

We also reduced unpredictable latency jitter on M2 caused by
the CPU entering and exiting various sleep states by running:
```
sudo tuned-adm profile latency-performance
```

### TCP RTT accuracy experiments
The main TCP accuracy experiments, which compare the RTTs reported by
PPing, ePPing and tshark, require that the [extra-output/RTT
accuracy](https://doi.org/10.5281/zenodo.7573207) build is used. The
experiment from the paper can be repeated by running:
```
./run_tcp_accuracy_test.sh <directory-to-save-results-in>
```

We also ran this test with slightly modified parameters to highlight
some of the effects of using TCP timestamps to calculate the
RTTs in the appendix. The example provided in the appendix was created
by running:
```
IPERF3_FLAGS="-Z -b 100M --pacing-time 50000 -t 3600" \
NETEM_DELAYS="50ms" PER_DELAY_TEST_LENGTH=100 \
./run_tcp_accuracy_test.sh <directory-to-save-results-in>
```

### Performance experiments
The performance experiments were performed with the
[main/performance](https://doi.org/10.5281/zenodo.7573173) build of
ePPing. To repeat the (multi-threaded) performance experiments in the
paper, simply run: 
``` 
PIN_CORE="" ./run_multiple_performance_tests.sh <directory-to-save-results-in> <repetitions>
``` 
Note that we used 10 repetitions for the experiments in the paper.

Most of the performance tests were done with the packet processing on
M2 pinned to a single core (to make the CPU at M2
the bottleneck). This can be achieved by for example running the
[set_irq_affinity.sh](https://github.com/Mellanox/mlnx-tools/blob/mlnx_ofed/sbin/set_irq_affinity_cpulist.sh)
script from the [mlnx-tools](https://github.com/Mellanox/mlnx-tools)
repository, ex:
```
sudo ./set_irq_affinity.sh 0 <interface>
```

We also limited the number of RX/TX channels by running:
```
sudo ethtool -L <interface> combined 1
```

Ensure that you then run the scripts with `PIN_CORE` set to the same
core as you've pinned the packet processing to. If not specified, it
assumes core 0. Thereafter you can simply run the
[run_multiple_performance_tests.sh](run_multiple_performance_tests.sh)
script again.

To replicate the experiments showing what impact different sampling
rate limits have on the performance, use the
[run_sampling_impact_test.sh](run_sampling_impact_test.sh) script. To
do the experiment with individual RTT reports, simply run it as:
```
./run_sampling_impact_test.sh <diretory-to-save-results-in> <repetitons>
```

To run it while using ePPing's aggregated output instead, use:
```
EPPING_BASE_ARGS="-I xdp -f -a 1" ./run_sampling_impact_test.sh <diretory-to-save-results-in> <repetitons>
```

