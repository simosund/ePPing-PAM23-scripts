#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later

# Test ePPing performance with various r-values (sampling rate limits)

source experiments.conf

EPPING_BASE_ARGS="-I xdp -f"
R_VALUES=${R_VALUES:-"0 10 100 1000"}

ADD_DATETIME_SUBPATH=${ADD_DATETIME_SUBPATH:-true}

# Sample rate limiting only relevant for ePPing, so skip baseline and PPing tests
export RUN_BASELINE=false
export RUN_KPPING=false
export RUN_EPPING=true 

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

export ADD_DATETIME_SUBPATH=false

for r in $R_VALUES; do
    echo -e "\n Running tests with r=${r}"
    
    r_dir="${basepath}/r_${r}"
    EPPING_FLAGS="$EPPING_BASE_ARGS -r $r" ./run_multiple_performance_tests.sh $r_dir $reps
done
