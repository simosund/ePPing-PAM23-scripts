#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later

# A script to run some iperf3 tests from M1->M3 without pping,
# with Kathie's pping and with my eBPF pping, collecting some
# results and generating some plots

# Author: Simon Sundberg

source experiments.conf

IPERF3_FLAGS=${IPERF3_FLAGS:-"-Z -t 120"}

# Arguments to use for PPing and ePPing (except interface)
KPPING_FLAGS=${KPPING_FLAGS:-"--sumInt 1"}
EPPING_FLAGS=${EPPING_FLAGS:-"-r 0 -I xdp -f"}

# The core to which PPing/ePPing should be pinned. Put as "" to not pin at all
PIN_CORE=${PIN_CORE:-0} 

# Which tests to run
RUN_BASELINE=${RUN_BASELINE:-true} # Do test with just forwarding
RUN_KPPING=${RUN_KPPING:-true}     # Do test with Kathie's PPing
RUN_EPPING=${RUN_EPPING:-true}     # Do test with ePPing

# Time to wait between starting new test in seconds
INTERTEST_INTERVAL=${INTERTEST_INTERVAL:-10} 

export MPLBACKEND=agg

# $1 = path to save results in
# $2 = number of flows

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

start_system_monitoring() {
    local save_path=$1

    for M in $M1 $M2 $M3; do
        start_sar $M $save_path
    done

    start_tcp_monitoring $M1 $save_path

    sleep 2 # Give the monitoring some time to set up
}

stop_system_monitoring() {
    for M in $M1 $M2 $M3; do
        stop_sar $M
    done

    stop_tcp_monitoring $M1
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

run_iperf3_clients() {
    local machine=$1
    local save_path=$2
    local n_flows=$3

    echo "${machine}: Running iperf3 tests..."

    local CMD="mkdir -p $save_path; echo "\""Start: \$(TZ=UTC date -Iseconds)"\"" > ${save_path}/test_interval.log; "
    for ((i=0; i < IPERF_INSTANCES; i++)); do
        local N=$(( (n_flows / IPERF_INSTANCES) + (i < n_flows % IPERF_INSTANCES) ))
        if (( N > 0 )); then
            CMD+="iperf3 -c $IP_TARGET -p $(( IPERF_PORT_START + i )) -P $N $IPERF3_FLAGS --json > ${save_path}/iperf_${i}.json & "
        fi
    done

    CMD=${CMD%' & '}
    CMD+="; echo "\""End: \$(TZ=UTC date -Iseconds)"\"" >> ${save_path}/test_interval.log"

    ssh $machine "$CMD"
}

start_kpping() {
    # Kathie's pping
    local machine=$1
    local save_path=$2

    echo "${machine}: Setting up Kathie's pping on ${IFACE}..."

    local pin_cmd=""
    if [[ -n "$PIN_CORE" ]]; then
	pin_cmd="taskset -c $PIN_CORE"
    fi

    local CMD="mkdir -p $save_path; "
    CMD+="TZ=UTC sudo nohup $pin_cmd ${KPPING_PATH}/pping -i $IFACE $KPPING_FLAGS > ${save_path}/pping.out 2> ${save_path}/pping.err &"
    ssh $machine "$CMD"
    sleep 2 # Give pping some time to set up
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

run_test() {
    local save_path=$1
    local n_flows=$2

    mkdir -p $save_path

    start_iperf3_servers $M3
    start_system_monitoring $save_path

    run_iperf3_clients $M1 $save_path $n_flows

    sleep 1

    stop_system_monitoring
    stop_iperf3_servers $M3
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


# main
if (( $# != 2 )); then
    echo "Usage: $0 <save_path> <n_flows>"
    exit 1
fi

base_path=$1
n_flows=$2

if [[ "$RUN_BASELINE" != true && "$RUN_KPPING" != true && "$RUN_EPPING" != true ]]; then
    echo "Error - no test to run (at least one of RUN_BASELINE, RUN_KPPING or RUN_EPPING should be set to true)"
    exit
fi

if (( $n_flows > 128 * $IPERF_INSTANCES )); then
    echo "Error - cannot create $n_flows concurrent flows with just $IPERF_INSTANCES instances of iperf3"
    exit 1
fi

if [[ "$RUN_BASELINE" == true ]]; then
    echo "Running test with no pping..."
    test_path="${base_path}/no_pping"
    run_test $test_path $n_flows
    copy_back_results $test_path

    sleep $INTERTEST_INTERVAL
fi

if [[ "$RUN_KPPING" == true ]]; then
    echo -e "\n\nRunning test with Kathie's pping..."
    test_path="${base_path}/k_pping"
    start_kpping $M2 $test_path
    run_test $test_path $n_flows
    stop_pping $M2
    copy_back_results $test_path
    
    sleep $INTERTEST_INTERVAL
fi

if [[ "$RUN_EPPING" == true ]]; then
    echo -e "\n\nRunning test with my eBPF pping..."
    test_path="${base_path}/e_pping"
    start_epping $M2 $test_path
    run_test $test_path $n_flows
    stop_pping $M2
    copy_back_results $test_path
fi

IFACE=$IFACE ./plot_results.sh $base_path $IP_TARGET
