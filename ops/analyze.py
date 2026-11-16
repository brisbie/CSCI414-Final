#!/usr/bin/env python3

import argparse
import csv
import glob
import json
import os
import re
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ORDER = ["baseline", "delay", "loss", "rate", "congested", "dbdelay", "combo"]
COLORS = {"baseline": "#2a9d8f", "delay": "#e9c46a", "loss": "#f4a261", "rate": "#8ab17d",
          "congested": "#e76f51", "dbdelay": "#577590", "combo": "#6d597a"}


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def fnum(x, nd=1):
    return "–" if x is None else f"{x:.{nd}f}"


def read_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def parse_ping(path):
    if not os.path.exists(path):
        return {}
    t = open(path).read()
    out = {}
    m = re.search(r"([\d.]+)% packet loss", t)
    if m:
        out["ping_loss_pct"] = float(m.group(1))
    m = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms", t)
    if m:
        out.update(rtt_min_ms=float(m.group(1)), rtt_avg_ms=float(m.group(2)),
                   rtt_max_ms=float(m.group(3)), rtt_mdev_ms=float(m.group(4)))
    out["ping_samples"] = len(re.findall(r"icmp_seq=", t))
    return out


def parse_curl(path):
    if not os.path.exists(path):
        return {}
    rows = [r for r in read_rows(path) if r.get("http_code") == "200"]
    if not rows:
        return {"curl_ok": 0}
    c = [float(r["time_connect"]) * 1000 for r in rows]
    tls = [(float(r["time_appconnect"]) - float(r["time_connect"])) * 1000 for r in rows]
    tot = [float(r["time_total"]) * 1000 for r in rows]
    return {"curl_ok": len(rows), "tcp_connect_ms": statistics.median(c),
            "tls_handshake_ms": statistics.median(tls), "fresh_request_ms": statistics.median(tot)}


def parse_iperf(path):
    if not os.path.exists(path):
        return {}
    try:
        j = json.load(open(path))
        end = j["end"]
        return {"throughput_mbps": end["sum_received"]["bits_per_second"] / 1e6,
                "iperf_retransmits": end["sum_sent"].get("retransmits")}
    except (ValueError, KeyError):
        return {}


def parse_kv(path):
    out = {}
    if os.path.exists(path):
        for line in open(path):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                try:
                    out[k] = int(v)
                except ValueError:
                    out[k] = v
    return out


def load_condition(d):
    rows = read_rows(os.path.join(d, "loadgen.csv"))
    for r in rows:
        r["ok"] = r["ok"] == "True"
        r["total_ms"] = float(r["total_ms"])
        r["app_ms"] = float(r["app_ms"]) if r["app_ms"] not in ("", "None") else None
        r["db_ms"] = float(r["db_ms"]) if r["db_ms"] not in ("", "None") else None
    ok = [r for r in rows if r["ok"]]
    lat = [r["total_ms"] for r in ok]
    app = [r["app_ms"] for r in ok if r["app_ms"] is not None]
    dbm = [r["db_ms"] for r in ok if r["db_ms"] is not None]
    net = [r["total_ms"] - r["app_ms"] for r in ok if r["app_ms"] is not None]
    summ = json.load(open(os.path.join(d, "summary.json")))
    s = {
        "condition": os.path.basename(d), "requests": len(rows), "success": len(ok),
        "error_rate_pct": 100.0 * (len(rows) - len(ok)) / len(rows) if rows else None,
        "mean_ms": statistics.mean(lat) if lat else None,
        "p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95), "p99_ms": pct(lat, 99),
        "max_ms": max(lat) if lat else None,
        "median_db_ms": pct(dbm, 50), "median_app_nondb_ms": (pct(app, 50) or 0) - (pct(dbm, 50) or 0),
        "median_network_ms": pct(net, 50),
        "throughput_rps": summ.get("throughput_rps"),
    }
    s.update(parse_ping(os.path.join(d, "ping.txt")))
    s.update(parse_curl(os.path.join(d, "curl_timing.csv")))
    s.update(parse_iperf(os.path.join(d, "iperf.json")))
    cap = parse_kv(os.path.join(d, "capture_stats.txt"))
    for k in ("frames", "retransmissions", "duplicate_acks", "out_of_order"):
        if k in cap:
            s[f"pcap_{k}"] = cap[k]
    s["_lat"] = lat
    s["_by_op"] = summ.get("by_op", {})
    return s


def charts(conds, outdir):
    os.makedirs(outdir, exist_ok=True)
    names = [c["condition"] for c in conds]
    col = [COLORS.get(n, "#888") for n in names]

    # 1. percentiles
    fig, ax = plt.subplots(figsize=(8, 4.2))
    w = 0.26
    xs = range(len(conds))
    for k, (key, lab) in enumerate([("p50_ms", "p50"), ("p95_ms", "p95"), ("p99_ms", "p99")]):
        ax.bar([x + (k - 1) * w for x in xs], [c[key] or 0 for c in conds], w, label=lab,
               color=["#264653", "#2a9d8f", "#e76f51"][k])
    ax.set_xticks(list(xs), names)
    ax.set_ylabel("request latency (ms)")
    ax.set_title("Application request latency by network condition (identical workload)")
    ax.legend(frameon=False, loc="upper left")
    ax.grid(axis="y", alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "latency_percentiles.png"), dpi=150)
    plt.close(fig)

    # 2. breakdown (median)
    fig, ax = plt.subplots(figsize=(8, 4.2))
    db_ = [c["median_db_ms"] or 0 for c in conds]
    app = [max(c["median_app_nondb_ms"] or 0, 0) for c in conds]
    net = [max(c["median_network_ms"] or 0, 0) for c in conds]
    ax.bar(names, db_, label="MongoDB query", color="#264653")
    ax.bar(names, app, bottom=db_, label="API processing (non-DB)", color="#2a9d8f")
    ax.bar(names, net, bottom=[a + b for a, b in zip(db_, app)], label="network + TLS + client", color="#e76f51")
    ax.set_ylabel("median latency (ms)")
    ax.set_title("Where the time goes: network vs application vs database")
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1))
    ax.grid(axis="y", alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "latency_breakdown.png"), dpi=150)
    plt.close(fig)

    # 3. CDF
    fig, ax = plt.subplots(figsize=(8, 4.2))
    for c, cc in zip(conds, col):
        lat = sorted(c["_lat"])
        if lat:
            ax.plot(lat, [(i + 1) / len(lat) for i in range(len(lat))], label=c["condition"], color=cc, lw=2)
    ax.set_xscale("log")
    ax.set_xlabel("request latency (ms, log scale)")
    ax.set_ylabel("fraction of requests")
    ax.set_title("Latency distribution (CDF)")
    ax.legend(frameon=False)
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "latency_cdf.png"), dpi=150)
    plt.close(fig)

    # 4. network metrics
    fig, axs = plt.subplots(1, 3, figsize=(12, 3.8))
    axs[0].bar(names, [c.get("rtt_avg_ms") or 0 for c in conds], color=col)
    axs[0].set_title("ICMP RTT avg (ms)")
    axs[1].bar(names, [c.get("tls_handshake_ms") or 0 for c in conds], color=col)
    axs[1].set_title("TLS handshake, median (ms)")
    axs[2].bar(names, [c.get("throughput_mbps") or 0 for c in conds], color=col)
    axs[2].set_title("iperf3 TCP throughput (Mbit/s, log)")
    axs[2].set_yscale("log")
    for a in axs:
        a.tick_params(axis="x", rotation=30)
        a.grid(axis="y", alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "network_metrics.png"), dpi=150)
    plt.close(fig)


def write_tables(conds, run):
    cols = ["condition", "requests", "success", "error_rate_pct", "mean_ms", "p50_ms", "p95_ms", "p99_ms",
            "max_ms", "median_db_ms", "median_app_nondb_ms", "median_network_ms", "throughput_rps",
            "rtt_avg_ms", "rtt_mdev_ms", "ping_loss_pct", "tcp_connect_ms", "tls_handshake_ms",
            "throughput_mbps", "iperf_retransmits", "pcap_frames", "pcap_retransmissions", "pcap_duplicate_acks"]
    with open(os.path.join(run, "summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for c in conds:
            w.writerow([round(c[k], 3) if isinstance(c.get(k), float) else c.get(k, "") for k in cols])

    md = ["## Application latency (client-side, ms; identical seeded workload per condition)", "",
          "| Condition | OK / total | Error % | Mean | p50 | p95 | p99 | Max | Throughput (req/s) |",
          "|---|---|---|---|---|---|---|---|---|"]
    for c in conds:
        md.append(f"| {c['condition']} | {c['success']}/{c['requests']} | {fnum(c['error_rate_pct'], 2)} | "
                  f"{fnum(c['mean_ms'])} | {fnum(c['p50_ms'])} | {fnum(c['p95_ms'])} | {fnum(c['p99_ms'])} | "
                  f"{fnum(c['max_ms'])} | {fnum(c['throughput_rps'], 2)} |")
    md += ["", "## Latency breakdown (medians, ms)", "",
           "| Condition | MongoDB | API non-DB | Network + TLS + client | Total p50 |", "|---|---|---|---|---|"]
    for c in conds:
        md.append(f"| {c['condition']} | {fnum(c['median_db_ms'], 2)} | {fnum(c['median_app_nondb_ms'], 2)} | "
                  f"{fnum(c['median_network_ms'], 2)} | {fnum(c['p50_ms'], 2)} |")
    md += ["", "## Network-level measurements", "",
           "| Condition | ICMP RTT avg (ms) | RTT mdev (ms) | Ping loss % | TCP connect (ms) | TLS handshake (ms) "
           "| iperf3 (Mbit/s) | iperf3 retrans | pcap retrans | pcap dup ACKs |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for c in conds:
        md.append(f"| {c['condition']} | {fnum(c.get('rtt_avg_ms'), 2)} | {fnum(c.get('rtt_mdev_ms'), 2)} | "
                  f"{fnum(c.get('ping_loss_pct'), 1)} | {fnum(c.get('tcp_connect_ms'), 2)} | "
                  f"{fnum(c.get('tls_handshake_ms'), 2)} | {fnum(c.get('throughput_mbps'), 2)} | "
                  f"{c.get('iperf_retransmits', '–')} | {c.get('pcap_retransmissions', '–')} | "
                  f"{c.get('pcap_duplicate_acks', '–')} |")
    md += ["", "## p50 latency per operation (ms)", ""]
    ops = ["list_products", "get_product", "create_order", "get_order", "pay_order"]
    md += ["| Condition | " + " | ".join(ops) + " |", "|---" * (len(ops) + 1) + "|"]
    for c in conds:
        md.append(f"| {c['condition']} | " + " | ".join(fnum(c['_by_op'].get(o, {}).get('p50_ms')) for o in ops) + " |")
    open(os.path.join(run, "summary.md"), "w").write("\n".join(md) + "\n")
    return "\n".join(md)


def recovery(run, monitor_csv, chart_dir):
    files = sorted(glob.glob(os.path.join(run, "recovery", "*.csv")))
    if not files:
        return ""
    recs = [r for f in files for r in read_rows(f)]
    mon = read_rows(monitor_csv) if monitor_csv and os.path.exists(monitor_csv) else []
    md = ["## Failure and recovery", "",
          "| Scenario | Detected after (s) | Healing action | Service restored after (s) | Total outage seen by client (s) "
          "| Monitor-observed outage (s) | Verify request |",
          "|---|---|---|---|---|---|---|"]
    for r in recs:
        t_fail, t_rec = float(r["t_fail"]), float(r["t_recovered"])
        mon_out = "–"
        # Scenarios run ~5 s apart, so keep the window tight to avoid the previous outage
        win = [m for m in mon if t_fail - 4 <= float(m["epoch"]) <= t_rec + 4]
        if win:
            after = [m for m in win if float(m["epoch"]) >= t_fail]
            first_down = next((float(m["epoch"]) for m in after if m["ok"] == "0"), None)
            if first_down is not None:
                back = next((float(m["epoch"]) for m in after if m["ok"] == "1" and float(m["epoch"]) > first_down), None)
                if back is not None:
                    mon_out = f"{back - first_down:.1f}"
            fig, ax = plt.subplots(figsize=(8, 3.6))
            ts = [float(m["epoch"]) - t_fail for m in win]
            okp = [(t, float(m["latency_ms"])) for m, t in zip(win, ts) if m["ok"] == "1"]
            badp = [(t, float(m["latency_ms"])) for m, t in zip(win, ts) if m["ok"] == "0"]
            if okp:
                ax.plot(*zip(*okp), "o", ms=3, color="#264653", label="healthy probe")
            if badp:
                ax.plot(*zip(*badp), "x", ms=5, color="#e76f51", label="failed probe")
            for m, t in zip(win, ts):
                if m["ok"] == "0":
                    ax.axvspan(t - 0.25, t + 0.25, color="#e76f51", alpha=.25, lw=0)
            for key, lab, c in [("t_detect", "detected", "#e9c46a"), ("t_heal_start", "heal", "#2a9d8f"),
                                ("t_recovered", "recovered", "#264653")]:
                ax.axvline(float(r[key]) - t_fail, color=c, ls="--", label=lab)
            ax.axvline(0, color="#e76f51", ls="-", label="failure injected")
            ax.set_xlabel("seconds since failure injected")
            ax.set_ylabel("health probe (ms)")
            ax.set_title(f"Recovery timeline: {r['scenario']} (red = failed probes)")
            ax.legend(frameon=False, fontsize=7, ncol=6, loc="upper center", bbox_to_anchor=(0.5, -0.22))
            ax.grid(alpha=.3)
            fig.tight_layout()
            fig.savefig(os.path.join(chart_dir, f"recovery_{r['scenario']}.png"), dpi=150)
            plt.close(fig)
        md.append(f"| {r['scenario']} | {float(r['detect_s']):.1f} | {r['action']} | {float(r['recover_s']):.1f} | "
                  f"{float(r['outage_s']):.1f} | {mon_out} | {r['verify']} |")
    text = "\n".join(md) + "\n"
    open(os.path.join(run, "recovery.md"), "w").write(text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--monitor", default="/logs/monitor.csv")
    a = ap.parse_args()
    dirs = [d for d in glob.glob(os.path.join(a.run, "*")) if os.path.exists(os.path.join(d, "loadgen.csv"))]
    dirs.sort(key=lambda d: ORDER.index(os.path.basename(d)) if os.path.basename(d) in ORDER else 99)
    chart_dir = os.path.join(a.run, "charts")
    os.makedirs(chart_dir, exist_ok=True)
    if dirs:
        conds = [load_condition(d) for d in dirs]
        charts(conds, chart_dir)
        print(write_tables(conds, a.run))
    rec = recovery(a.run, a.monitor, chart_dir)
    if rec:
        print(rec)
    if not dirs and not rec:
        raise SystemExit(f"nothing to analyze in {a.run}")
    print(f"\n[analyze] wrote summary.csv, summary.md, recovery.md and charts/ in {a.run}")


if __name__ == "__main__":
    main()
