#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later

# A modification of the run_performance_test script, Instead of running a test
# without monitoring (baseline), one with PPing and one with ePPing, it only
# runs a test with ePPing + tcpdump at the same time. Furthermore, it sets
# up a netem qdisc at M3 and updates it every PER_DELAY_TEST_LENGTH interval to
# a new delay in NETEM_DELAYS (and automatically ends the test one all delays
# have been tested)

# To be able to analyze the results properly the build from
# https://doi.org/10.5281/zenodo.7573207 must be used, which adds TSecr
# and ACK no. to the output.

# Author: Simon Sundberg

source experiments.conf

IPERF3_FLAGS=${IPERF3_FLAGS:-"-Z --fq-rate 100M -t 3600"} # Set test duratiion really long, iperf automatically killed by script when done
EPPING_FLAGS=${EPPING_FLAGS:-"-r 0 -I xdp -f -F ppviz"} # The TSecr and ACK numbers where only added to the ppviz format

PIN_CORE=${PIN_CORE:-""}

# Which netem delays to use
NETEM_DELAYS=${NETEM_DELAYS:-"0ms 10ms 20ms 30ms 40ms 50ms 60ms 70ms 80ms 90ms 100ms"}
# Which machine to setup netem on
NETEM_MACHINE=${NETEM_MACHINE:-$M3}
# Which interface on $NETEM_MACHINE to setup netem on
NETEM_IFACE=${NETEM_IFACE:-"enp1s0f1np1"}
# Arguments to TCPDUMP (except --interface)
TCPDUMP_ARGS="-s 96"

# Length (in seconds) to run the test at each netem delay
PER_DELAY_TEST_LENGTH=${PER_DELAY_TEST_LENGTH:-10}

ADD_DATETIME_SUBPATH=${ADD_DATETIME_SUBPATH:-true}

export MPLBACKEND=agg

start_sar() {
    local machine=$1
    local save_path=$2

    echo "${machine}: Starting sar..."
    ssh $machine "mkdir -p $save_path; TZ=UTC nohup sar -o ${save_path}/${GENERIC_MACHINE_NAMES[$machine]}_stats.sar 1 > /dev/null 2>&1 &"
}

stop_sar() {
    local machine=$1

    echo "${machine}: Stopping sar..."

    # The ^ in the begining of pkill -f ^sar is to ensure it will only match
    # against processes starting with sar rather than containing sar anywhere
    # in its arguments, thus preventing it from killing this command itself
    ssh $machine 'pkill -u $(whoami) -f "^sar -o .*_stats.sar"'
}

start_tcp_monitoring() {
    local machine=$1
    local save_path=$2
    local interval=${3:-1}
    
    local CMD="mkdir -p $save_path;"
    CMD+=" watch -pn $interval "\""(TZ=UTC date +%Y-%m-%dT%H:%M:%S; ss -tinHO) >> ${save_path}/ss_tcp.log"\"" &> /dev/null"

    echo "${machine}: Starting TCP monitoring (periodic ss -ti)..."
    ssh -tt $machine "$CMD" &
}

stop_tcp_monitoring() {
    local machine=$1

    echo "${machine}: Stopping tcp monitoring..."
    ssh $machine 'pkill -u $(whoami) -f "^watch.* ss -ti"'
}

start_tcpdump() {
    local machine=$1
    local savepath=$2
    local iface=${3:-$IFACE}
    local tcpdump_args=${4:-$TCPDUMP_ARGS}

    local CMD="mkdir -p $savepath; "
    CMD+="TZ=UTC sudo nohup tcpdump -i $iface -w ${savepath}/packetdump.pcap $tcpdump_args > ${savepath}/tcpdump_info.txt 2>&1 &"

    echo "${machine}: Starting tcpdump with args: $tcpdump_args"
    ssh $machine "$CMD"
}

stop_tcpdump() {
    local machine=$1
    local iface=${2:-$IFACE}

    echo "${machine}: Stopping tcpdump -i $iface"
    ssh $machine "sudo pkill -f '^tcpdump -i $iface'"
}

start_system_monitoring() {
    local save_path=$1

    for M in $M1 $M2 $M3; do
        start_sar $M $save_path
    done

    start_tcp_monitoring $M1 $save_path
    start_tcpdump $M2 $save_path

    sleep 2 # Give the monitoring some time to set up
}

stop_system_monitoring() {
    for M in $M1 $M2 $M3; do
        stop_sar $M
    done

    stop_tcp_monitoring $M1
    stop_tcpdump $M2
}

start_iperf3_servers() {
    local machine=$1
    
    echo "${machine}: Setting up iperf3 servers..."

    local CMD=""
    for ((i=0; i < IPERF_INSTANCES; i++)); do
        CMD+="nohup iperf3 -s -p $(( IPERF_PORT_START + i)) > /dev/null 2>&1 & "
    done

    ssh $machine "$CMD"
    sleep 1
}

stop_iperf3_servers() {
    local machine=$1
    
    echo "${machine}: Killing iperf3 servers"
    ssh $machine 'pkill -u $(whoami) -f "^iperf3 -s"'
}

start_iperf3_clients() {
    local machine=$1
    local save_path=$2
    local n_flows=$3

    echo "${machine}: Running iperf3 tests..."

    local CMD="mkdir -p $save_path; echo "\""Start: \$(TZ=UTC date -Iseconds)"\"" > ${save_path}/test_interval.log; "
    for ((i=0; i < IPERF_INSTANCES; i++)); do
        local N=$(( (n_flows / IPERF_INSTANCES) + (i < n_flows % IPERF_INSTANCES) ))
        if (( N > 0 )); then
            CMD+="nohup iperf3 -c $IP_TARGET -p $(( IPERF_PORT_START + i )) -P $N $IPERF3_FLAGS --json > ${save_path}/iperf_${i}.json 2> /dev/null & "
        fi
    done

    ssh $machine "$CMD"
}

stop_iperf3_clients() {
    local machine=$1
    local save_path=$2

    echo "${machine}: Killing iperf3 clients"
    CMD='pkill -u $(whoami) -f "^iperf3 -c"'
    CMD+="; echo "\""End: \$(TZ=UTC date -Iseconds)"\"" >> ${save_path}/test_interval.log"
    ssh $machine "$CMD"
}


start_epping() {
    # My eBPF pping
    local machine=$1
    local save_path=$2

    echo "${machine}: Settig up eBPF pping on ${IFACE}..."

    local pin_cmd=""
    if [[ -n "$PIN_CORE" ]]; then
	pin_cmd="taskset -c $PIN_CORE"
    fi    

    local CMD="mkdir -p $save_path; cd $EPPING_PATH; "
    CMD+="TZ=UTC sudo nohup $pin_cmd ./pping -i $IFACE $EPPING_FLAGS > ~/${save_path}/pping.out 2> ~/${save_path}/pping.err &"
    ssh $machine "$CMD"
    sleep 2 # Give pping some time to set up
}

stop_pping() {
    local machine=$1
    local iface=${2:-$IFACE}

    echo "${machine}: Stopping (e)PPing on $iface"

    # The brackets around [p] is used to avoid pkill -f from matching against
    # this command itself (and thus kill this ssh-command). The [p]ping pattern
    # will match against pping but not [p]ping
    ssh $machine "sudo pkill -f '[p]ping -i $iface'"
}

setup_netem() {
    local machine=$1
    local iface=${2:-$NETEM_IFACE}
    local netem_args=${3:-$NETEM_ARGS}

    echo "${machine}: Setting up netem $netem_args on dev $iface"
    ssh $machine "sudo tc qdisc add dev $iface root netem $netem_args"
}

change_netem() {
    local machine=$1
    local iface=${2:-$NETEM_IFACE}
    local netem_args=${3:-$NETEM_ARGS}

    echo "${machine}: Changing netem to $netem_args on dev $iface"
    ssh $machine "sudo tc qdisc change dev $iface root netem $netem_args"
}

teardown_netem() {
    local machine=$1
    local iface=${2:-$NETEM_IFACE}

    echo "${machine}: Removing netem from dev ${iface}"
    ssh $machine "sudo tc qdisc del dev $iface root netem"
}

start_test() {
    local save_path=$1
    local n_flows=${2:-1}

    mkdir -p $save_path

    start_epping $M2 $save_path
    start_iperf3_servers $M3
    start_system_monitoring $save_path
    sleep 1

    start_iperf3_clients $M1 $save_path $n_flows
}

stop_test() {
    local save_path=$1

    stop_iperf3_clients $M1 $save_path
    sleep 1

    stop_system_monitoring
    stop_iperf3_servers $M3
    stop_pping $M2
    sleep 1
}

copy_back_results() {
    local save_path=$1

    echo "Copying back results to local machine..."

    for M in $M1 $M2 $M3; do
	local subfolder=${save_path}/${GENERIC_MACHINE_NAMES[$M]}
        mkdir -p $subfolder
        ssh $M "xz -T0 ${save_path}/*"
        scp -p "${M}:${save_path}/*" "${subfolder}/"
        ssh $M "rm -r ${save_path}"
    done

    xz -d ${save_path}/${GENERIC_MACHINE_NAMES[$M1]}/test_interval.log.xz
    mv ${save_path}/${GENERIC_MACHINE_NAMES[$M1]}/test_interval.log -t $save_path
}


basepath=$1
n_flows=1

if (( $# != 1 )); then
    echo "Usage: $0 <save_path>"
    exit 1
fi

if (( $n_flows > 128 * $IPERF_INSTANCES )); then
    echo "Error - cannot create $n_flows concurrent flows with just $IPERF_INSTANCES instances of iperf3"
    exit 1
fi

if [[ "$ADD_DATETIME_SUBPATH" == true ]]; then
   currtime=$(date +%Y-%m-%dT%H%M%S)
   basepath=${basepath}/${currtime}
fi

is_first=true
for delay in $NETEM_DELAYS; do
    if [[ "$is_first" == true ]]; then
	setup_netem $NETEM_MACHINE $NETEM_IFACE "delay $delay"
	start_test "${basepath}/e_pping" $n_flows
	is_first=false
    else
	change_netem $NETEM_MACHINE $NETEM_IFACE "delay $delay"
    fi
    sleep $PER_DELAY_TEST_LENGTH
done

stop_test "${basepath}/e_pping"
teardown_netem $NETEM_MACHINE $NETEM_IFACE
copy_back_results "${basepath}/e_pping"
IFACE=$IFACE OMIT=0 ./plot_results.sh $basepath $IP_TARGET
