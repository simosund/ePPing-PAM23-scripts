# SPDX-License-Identifier: GPL-2.0-or-later
import pandas as pd
import scapy.all as scapy

import util
import sar_data_loading as sdl


U32_MAX = 1 << 32
U32_HALF = 1 << 31


def uint32_wraparound(a):
    return int(a) % U32_MAX


def uint32_geq(a, b):
    """ a >= b with u32 wraparound """
    return 0 <= uint32_wraparound(int(a) - int(b)) < U32_HALF


def uint32_grt(a, b):
    """ a > b with u32 wraparound """
    return 0 < uint32_wraparound(int(a) - int(b)) < U32_HALF


def scapy_get_flow_label(packet):
    ip = packet.getlayer("IP")
    tcp = packet.getlayer("TCP")
    if ip is not None and tcp is not None:
        return "{}:{}+{}:{}".format(ip.src, tcp.sport, ip.dst, tcp.dport)
    return ""


def scapy_get_tcp_timestamps(tcp_layer):
    for opt in tcp_layer.options:
        if opt[0] == "Timestamp":
            return opt[1]
    return -1, -1


def scapy_get_tcp_payload_length(packet):
    ip = packet.getlayer("IP")
    tcp = packet.getlayer("TCP")
    payload = ip.len - 4 * ip.ihl - 4 * tcp.dataofs

    # For sequence number analysis, SYN and FIN count as 1 byte of payload
    if "S" in str(tcp.flags) or "F" in str(tcp.flags):
        payload += 1
    return payload


def get_reverse_flow(flow_label):
    src, dst = flow_label.split("+")
    return dst + "+" + src


def _find_unsync_tsval_update(pcap_file, max_packets=None, verbose=True):
    flowcount = dict()
    flowstate = dict()
    uniq_tsval = dict()
    perr = dict()
    aerr = dict()
    errors = list()

    for i, packet in enumerate(scapy.PcapReader(pcap_file)):
        if max_packets is not None and i > max_packets:
            break

        tcp = packet.getlayer("TCP")
        if tcp is None:
            continue

        tsval, tsecr = scapy_get_tcp_timestamps(tcp)
        if tsval < 0 or tsecr < 0:
            continue

        flow = scapy_get_flow_label(packet)
        rev_flow = get_reverse_flow(flow)
        flowcount[flow] = flowcount.get(flow, 0) + 1

        # create flowstate
        if flow not in flowstate:
            flowstate[flow] = {"last_TSval": None, "TSval_switches": dict(),
                               "inflated_RTT_tsval": dict(), "seq_0": tcp.seq}

        fs = flowstate[flow]
        p_size = scapy_get_tcp_payload_length(packet)
        eack = uint32_wraparound(tcp.seq + p_size)

        # new TSval
        if p_size > 0 and (fs["last_TSval"] is None or uint32_grt(tsval, fs["last_TSval"])):
            fs["last_TSval"] = tsval
            fs["TSval_switches"][tsval] = {"ack": tcp.ack,
                                           "seq": tcp.seq,
                                           "eack": eack}
            uniq_tsval[flow] = uniq_tsval.get(flow, 0) + 1

        # Check how TSecr match against reverse flow
        if rev_flow not in flowstate:
            continue

        rev_fs = flowstate[rev_flow]

        # Delete state for all TSval that have already been matched
        for r_tsval in list(rev_fs["TSval_switches"].keys()):
            if uint32_geq(tsecr, r_tsval):
                del rev_fs["TSval_switches"][r_tsval]

        # Check if acking old TSval (potential error)
        for r_tsval, r_tsdata in rev_fs["TSval_switches"].items():
            if uint32_grt(r_tsval, tsecr) and uint32_geq(tcp.ack, r_tsdata["eack"]):
                if verbose:
                    print("Potential error: {} - {}: TSecr: {} < {} and ACK {} >= {}".format(
                        i, flow, tsecr, r_tsval, tcp.ack, r_tsdata["eack"]))
                perr[flow] = perr.get(flow, 0) + 1
                rev_fs["inflated_RTT_tsval"][r_tsval] = tcp.ack

        # Check if troublesome TSecr is seen (actual error)
        if tsecr in rev_fs["inflated_RTT_tsval"]:
            if verbose:
                print("ERROR!: {} - {}: TSecr {}".format(i, flow, tsecr))
            aerr[flow] = aerr.get(flow, 0) + 1
            errors.append({"packet_index": i, "flow": flow, "TSecr": tsecr, "ack": tcp.ack})
            del rev_fs["inflated_RTT_tsval"][tsecr]

    if verbose:
        print("{} packets from {} flows processed".format(i+1, len(flowcount)))
        print("{} potential and {} actual errors discovered".format(
            sum([flow_perr for flow_perr in perr.values()]), len(errors)))

    return {"flowcount": flowcount, "unique_TSvals": uniq_tsval,
            "potential_errors": perr, "actual_errors": aerr,
            "errors": errors, "flowstate": flowstate}


def _find_too_fast_retrans(pcap_file, max_packets=None, verbose=True):
    flowcount = dict()
    flowstate = dict()
    perr = dict()
    aerr = dict()
    perr_weak = dict()
    aerr_weak = dict()
    errors = list()
    weak_errors = list()

    for i, packet in enumerate(scapy.PcapReader(pcap_file)):
        if max_packets is not None and i > max_packets:
            break

        tcp = packet.getlayer("TCP")
        if tcp is None:
            continue

        tsval, tsecr = scapy_get_tcp_timestamps(tcp)
        if tsval < 0 or tsecr < 0:
            continue

        flow = scapy_get_flow_label(packet)
        rev_flow = get_reverse_flow(flow)
        flowcount[flow] = flowcount.get(flow, 0) + 1

        # create flowstate
        if flow not in flowstate:
            flowstate[flow] = {"last_byte_sent": None, "last_TSval": None, "TSval_switches": dict(), 
                               "partial_err_tsval": dict(), "err_tsval": dict(), "seq_0": tcp.seq}

        fs = flowstate[flow]
        p_size = scapy_get_tcp_payload_length(packet)
        eack = uint32_wraparound(tcp.seq + p_size)

        # New seq or retransmission?
        if p_size > 0 and (fs["last_byte_sent"] is None or uint32_grt(tcp.seq, fs["last_byte_sent"])):
            fs["last_byte_sent"] = uint32_wraparound(eack - 1)
        elif p_size > 0:  # Retrans
            # Retrans with same TSval as current outstanding TSval (potential_error)
            if tsval in fs["TSval_switches"]:
                if tcp.seq == fs["TSval_switches"][tsval]["seq"]:
                    fs["err_tsval"][tsval] = tcp.seq
                    perr[rev_flow] = perr.get(rev_flow, 0) + 1
                else:
                    fs["partial_err_tsval"][tsval] = tcp.seq
                    perr_weak[rev_flow] = perr_weak.get(rev_flow, 0) + 1

                if verbose:
                    print("Potential error: {} - {}: Retrans seq: {} - {}, TSval {}".format(
                        i, flow, tcp.seq, eack, tsval))

        # new TSval
        if p_size > 0 and (fs["last_TSval"] is None or uint32_grt(tsval, fs["last_TSval"])):
            fs["last_TSval"] = tsval
            fs["TSval_switches"][tsval] = {"ack": tcp.ack,
                                           "seq": tcp.seq,
                                           "eack": eack}

        # Check how TSecr match against reverse flow
        if rev_flow not in flowstate:
            continue

        rev_fs = flowstate[rev_flow]

        # Delete state for all TSval that have already been matched
        for r_tsval in list(rev_fs["TSval_switches"].keys()):
            if uint32_geq(tsecr, r_tsval):
                del rev_fs["TSval_switches"][r_tsval]

        # Check if acking retransmitted TSval (error)
        if tsecr in rev_fs["err_tsval"]:
            aerr[flow] = aerr.get(flow, 0) + 1
            errors.append({"packet_index": i, "flow": flow, "TSecr": tsecr, "ack": tcp.ack})
            del rev_fs["err_tsval"][tsecr]
            if verbose:
                print("ERROR!: {} - {}: TSecr {}".format(i, flow, tsecr))
        elif tsecr in rev_fs["partial_err_tsval"]:
            aerr_weak[flow] = aerr_weak.get(flow, 0) + 1
            weak_errors.append({"packet_index": i, "flow": flow, "TSecr": tsecr, "ack": tcp.ack})
            del rev_fs["partial_err_tsval"][tsecr]
            if verbose:
                print("ERROR (weak)!: {} - {}: TSecr {}".format(i, flow, tsecr))

    if verbose:
        print("{} packets from {} flows processed".format(i+1, len(flowcount)))
        print("{} potential and {} actual errors discovered".format(
            sum([flow_perr for flow_perr in perr.values()]), len(errors)))
        print("{} potential and {} actual weak errors discovered".format(
            sum([flow_perr for flow_perr in perr_weak.values()]), len(weak_errors)))
    return {"flowcount": flowcount, "potential_errors": perr,
            "actual_errors": aerr, "weak_potential_error": perr_weak,
            "weak_actual_errors": aerr_weak, "errors": errors,
            "weak_errors": weak_errors, "flowstate": flowstate}


def _calculate_rtts_from_pcap(pcap_file, max_packets=None, verbose=False):
    flowstate = dict()
    rtts = []

    for i, packet in enumerate(scapy.PcapReader(pcap_file)):
        if max_packets is not None and i > max_packets:
            break

        tcp = packet.getlayer("TCP")
        if tcp is None:
            continue

        tsval, tsecr = scapy_get_tcp_timestamps(tcp)

        flow = scapy_get_flow_label(packet)
        rev_flow = get_reverse_flow(flow)
        p_size = scapy_get_tcp_payload_length(packet)
        eack = uint32_wraparound(tcp.seq + p_size)

        # create flowstate
        if flow not in flowstate:
            flowstate[flow] = {"outstanding_packets": [],
                               "last_eack": tcp.seq,
                               "last_tsval": None,
                               "seq_0": tcp.seq}
        fs = flowstate[flow]

        # Add outgoing packets
        if p_size > 0:  # SYN and FIN adds 1 to the payload, so they are also included

            # Detect retrans
            retrans = False
            if uint32_geq(tcp.seq, fs["last_eack"]):
                fs["last_eack"] = eack
            else:
                retrans = True

            # Detect TSval shift
            new_tsval = False
            if tsval is not None and (fs["last_tsval"] is None or uint32_grt(tsval, fs["last_tsval"])):
                fs["last_tsval"] = tsval
                new_tsval = True

            fs["outstanding_packets"].append({"seq": tcp.seq,
                                              "eack": eack,
                                              "retrans": retrans,
                                              "tsval": tsval,
                                              "new_tsval": new_tsval,
                                              "time": packet.time})
            if verbose:
                print("{}: Adding - flow: {}, seq: {}, eack: {}, tsval: {}".format(
                    i+1, flow, tcp.seq, eack, tsval))

        # Match ACKs against previous packets in reverse direction
        if rev_flow not in flowstate:
            continue
        rev_fs = flowstate[rev_flow]

        if "A" not in str(tcp.flags):
            continue

        # Find packets that are acked and remove them from outstanding list
        ack_pkts = []
        rem_pkts = []
        for prev_pkt in rev_fs["outstanding_packets"]:
            if uint32_geq(tcp.ack, prev_pkt["eack"]):
                ack_pkts.append(prev_pkt)
                if verbose:
                    print("{}: Match against - ack: {}, seq: {}".format(i+1, tcp.ack, prev_pkt["seq"]))
            else:
                rem_pkts.append(prev_pkt)
        rev_fs["outstanding_packets"] = rem_pkts

        if len(ack_pkts) > 0:
            match_times = [pkt["time"] for pkt in ack_pkts]
            min_rtt = float(packet.time - max(match_times))
            max_rtt = float(packet.time - min(match_times))

            # Calculate rtt based on TCP timestamp if available
            timestamp_rtt = None
            for prev_pkt in ack_pkts:
                if prev_pkt["new_tsval"] and prev_pkt["tsval"] == tsecr:
                    timestamp_rtt = float(packet.time - prev_pkt["time"])
                    break

            rtts.append({"time": util.parse_unix_timestamp(str(packet.time)),
                         "flow": flow,
                         "min_rtt": min_rtt,
                         "max_rtt": max_rtt,
                         "timestamp_rtt": timestamp_rtt,
                         "rtt": min_rtt,  # add min_rtt as "rtt" as well to make default interaction with others easier
                         "ack": tcp.ack,
                         "tsecr": tsecr,
                         "retrans": any([pkt["retrans"] for pkt in ack_pkts])})
            if verbose:
                print("{}: RTT - flow: {}, min_rtt: {}, max_rtt: {}".format(i+1, flow, min_rtt, max_rtt))

    if len(rtts) == 0:
        return None
    return pd.DataFrame.from_records(rtts)


def find_unsync_tsval_update(pcap_file, **kwargs):
    return sdl._run_on_xz_file(_find_unsync_tsval_update, pcap_file, **kwargs)


def find_too_fast_retrans(pcap_file, **kwargs):
    return sdl._run_on_xz_file(_find_too_fast_retrans, pcap_file, **kwargs)


def calculate_rtts_from_pcap(pcap_file, **kwargs):
    return sdl._run_on_xz_file(_calculate_rtts_from_pcap, pcap_file, **kwargs)
