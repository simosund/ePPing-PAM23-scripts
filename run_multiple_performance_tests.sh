#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later

# Runs run_performance_test.sh several times with varying number of flows.
# Also repeats the tests multiple times

source experiments.conf

# Different number of flows to repeat the tests with
N_FLOWS=${N_FLOWS:-"1 10 100 1000"}

# Nr seconds to ignore at start of each test (give time for TCP cc, CPU freq and cache etc. to stabalize)
OMIT=${OMIT:-20}

# How long to wait between starting a new test
INTERTEST_INTERVAL=${INTERTEST_INTERVAL:-10} #sec

export OMIT
export INTERTEST_INTERVAL

export MPLBACKEND=agg

ADD_DATETIME_SUBPATH=${ADD_DATETIME_SUBPATH:-true}

if (( $# != 2 )); then
    echo "Usage: $0 <save_path> <repetitions>"
    exit 1
fi

basepath=$1
reps=$2

if [[ "$ADD_DATETIME_SUBPATH" == true ]]; then
   currtime=$(date +%Y-%m-%dT%H%M%S)
   basepath=${basepath}/${currtime}
fi

for (( i = 1; i <= $reps; i++ )); do
    echo -e "\n\nStarting run $i \n\n"

    for flows in $N_FLOWS; do
        echo -e "\nRun test with $flows flows\n"

        test_path="${basepath}/run_${i}/${flows}_streams"
        ./run_performance_test.sh $test_path $flows
        sleep $INTERTEST_INTERVAL
    done
done

echo -e "\nPlotting summarized statistics for all runs..."
./pping_summarize_viz.py -i $basepath -s $IP_TARGET -I $IFACE -O $OMIT
echo "Done!"
