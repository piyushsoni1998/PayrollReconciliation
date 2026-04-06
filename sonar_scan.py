"""
SonarQube Auto Scanner + Report Generator
------------------------------------------
This script:
  1. Runs sonar-scanner on your project
  2. Waits for analysis to complete
  3. Automatically fetches & saves sonar_report.json

Usage (VS Code terminal):
    python sonar_scan.py
"""

import subprocess
import urllib.request
import json
import base64
import os
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIGURATION ─────────────────────────────────────────
SONAR_URL   = os.getenv("SONAR_URL", "http://localhost:9000")
PROJECT_KEY = os.getenv("SONAR_PROJECT_KEY", "demo_project")
USERNAME    = os.getenv("SONAR_USERNAME", "admin")
PASSWORD    = os.getenv("SONAR_PASSWORD", "admin")
TOKEN       = os.getenv("SONAR_TOKEN", "")
OUTPUT_FILE = "sonar_report.json"

SCANNER_PATH = r"C:\Users\piyush.soni\Downloads\sonar-scanner\sonar-scanner-6.2.1.4610-windows-x64\bin\sonar-scanner.bat"

SCANNER_CMD = [
    SCANNER_PATH,
    f"-Dsonar.projectKey={PROJECT_KEY}",
    # "-Dsonar.sources=.",
    r"-Dsonar.sources=C:\Users\piyush.soni\Desktop\RFP_Tool",
    f"-Dsonar.host.url={SONAR_URL}",
    f"-Dsonar.token={TOKEN}",
    r"-Dsonar.exclusions=sonar_scan.py,sonar_report.json,*.json,.env,.sonar/**",
]

# ───────────────────────────────────────────────────────────

METRIC_KEYS = ",".join([
    "bugs", "vulnerabilities", "code_smells",
    "coverage", "lines_to_cover", "uncovered_lines",
    "duplicated_lines_density", "duplicated_lines", "duplicated_blocks",
    "ncloc", "lines", "statements", "files", "classes", "functions",
    "comment_lines", "comment_lines_density",
    "complexity", "cognitive_complexity",
    "security_hotspots", "sqale_index",
    "reliability_rating", "security_rating", "sqale_rating", "alert_status",
])


def auth_header():
    creds = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


def fetch(endpoint):
    req = urllib.request.Request(
        f"{SONAR_URL}{endpoint}",
        headers=auth_header()
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def val(measures, key, default="N/A"):
    for m in measures:
        if m["metric"] == key:
            return m.get("value", default)
    return default


def to_grade(raw):
    try:
        return {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}[str(int(float(raw)))]
    except Exception:
        return "N/A"


# ── Extracted helper functions to reduce cognitive complexity ──

def fetch_analysis_date():
    """Fetch and format last analysis date."""
    try:
        comp = fetch(f"/api/components/show?component={PROJECT_KEY}")
        raw  = comp["component"].get("analysisDate", "")
        if raw:
            dt = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
            return dt.isoformat(), dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return "N/A", "N/A"


def fetch_quality_gate(measures):
    """Fetch quality gate status and conditions."""
    try:
        qg = fetch(f"/api/qualitygates/project_status?projectKey={PROJECT_KEY}")
        status = qg["projectStatus"]["status"]
        conditions = [
            {
                "metric"         : c.get("metricKey"),
                "status"         : c.get("status"),
                "actual_value"   : c.get("actualValue"),
                "error_threshold": c.get("errorThreshold", "N/A"),
            }
            for c in qg["projectStatus"].get("conditions", [])
        ]
        return status, conditions
    except Exception:
        return val(measures, "alert_status", "N/A"), []


def parse_facets(facets):
    """Parse issues facets into type and severity dicts."""
    by_type, by_severity = {}, {}
    for facet in facets:
        if facet["property"] == "types":
            by_type = {v["val"]: v["count"] for v in facet["values"]}
        elif facet["property"] == "severities":
            by_severity = {v["val"]: v["count"] for v in facet["values"]}
    return by_type, by_severity


def fetch_issues():
    """Fetch open issues summary."""
    try:
        iss = fetch(
            f"/api/issues/search?componentKeys={PROJECT_KEY}"
            "&resolved=false&ps=1&facets=types,severities"
        )
        by_type, by_severity = parse_facets(iss.get("facets", []))
        return iss.get("total", "N/A"), by_type, by_severity
    except Exception:
        return "N/A", {}, {}


def build_report(measures, project_name, analysis_iso, analysis_fmt,
                 qg_status, qg_conditions, total_issues, by_type, by_severity):
    """Assemble the full report dictionary."""
    return {
        "report_metadata": {
            "generated_at"          : datetime.now().isoformat(),
            "generated_at_formatted": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sonarqube_server"      : SONAR_URL,
            "report_version"        : "2.0",
        },
        "project": {
            "key"               : PROJECT_KEY,
            "name"              : project_name,
            "last_analysis_date": analysis_fmt,
            "last_analysis_iso" : analysis_iso,
        },
        "quality_gate": {
            "status"    : qg_status,
            "passed"    : qg_status == "OK",
            "conditions": qg_conditions,
        },
        "metrics": {
            "reliability": {
                "bugs"         : val(measures, "bugs", "0"),
                "rating_letter": to_grade(val(measures, "reliability_rating", "1")),
                "rating_raw"   : val(measures, "reliability_rating", "1"),
            },
            "security": {
                "vulnerabilities"  : val(measures, "vulnerabilities", "0"),
                "security_hotspots": val(measures, "security_hotspots", "0"),
                "rating_letter"    : to_grade(val(measures, "security_rating", "1")),
                "rating_raw"       : val(measures, "security_rating", "1"),
            },
            "maintainability": {
                "code_smells"           : val(measures, "code_smells", "0"),
                "technical_debt_minutes": val(measures, "sqale_index", "0"),
                "rating_letter"         : to_grade(val(measures, "sqale_rating", "1")),
                "rating_raw"            : val(measures, "sqale_rating", "1"),
            },
            "coverage": {
                "coverage_percent": val(measures, "coverage", "0.0"),
                "lines_to_cover"  : val(measures, "lines_to_cover", "0"),
                "uncovered_lines" : val(measures, "uncovered_lines", "0"),
            },
            "duplications": {
                "duplicated_lines_percent": val(measures, "duplicated_lines_density", "0.0"),
                "duplicated_lines"        : val(measures, "duplicated_lines", "0"),
                "duplicated_blocks"       : val(measures, "duplicated_blocks", "0"),
            },
            "size": {
                "lines_of_code"        : val(measures, "ncloc", "0"),
                "total_lines"          : val(measures, "lines", "0"),
                "statements"           : val(measures, "statements", "0"),
                "files"                : val(measures, "files", "0"),
                "classes"              : val(measures, "classes", "0"),
                "functions"            : val(measures, "functions", "0"),
                "comment_lines"        : val(measures, "comment_lines", "0"),
                "comment_lines_percent": val(measures, "comment_lines_density", "0.0"),
            },
            "complexity": {
                "cyclomatic_complexity": val(measures, "complexity", "N/A"),
                "cognitive_complexity" : val(measures, "cognitive_complexity", "N/A"),
            },
        },
        "issues": {
            "total_open" : total_issues,
            "by_type"    : by_type,
            "by_severity": by_severity,
        },
    }


def print_summary(report, output_path):
    """Print report summary to console."""
    passed = report["quality_gate"]["passed"]
    mt     = report["metrics"]
    gate   = "PASSED" if passed else "FAILED"
    sep    = "=" * 52
    print("\n" + sep)
    print("  sonar_report.json saved!")
    print("  Location: " + output_path)
    print(sep)
    print("  Quality Gate     : " + gate)
    print("  Bugs             : " + mt["reliability"]["bugs"] + "  (" + mt["reliability"]["rating_letter"] + ")")
    print("  Vulnerabilities  : " + mt["security"]["vulnerabilities"] + "  (" + mt["security"]["rating_letter"] + ")")
    print("  Code Smells      : " + mt["maintainability"]["code_smells"] + "  (" + mt["maintainability"]["rating_letter"] + ")")
    print("  Coverage         : " + mt["coverage"]["coverage_percent"] + "%")
    print("  Lines of Code    : " + mt["size"]["lines_of_code"])
    print("  Hotspots         : " + mt["security"]["security_hotspots"])
    print(sep)


def generate_report():
    """Fetch SonarQube analysis results and save as JSON. Complexity: ≤15"""
    print("\n Fetching analysis results from SonarQube ...")

    measures_resp = fetch(
        f"/api/measures/component?component={PROJECT_KEY}&metricKeys={METRIC_KEYS}"
    )
    measures     = measures_resp["component"]["measures"]
    project_name = measures_resp["component"].get("name", PROJECT_KEY)

    analysis_iso, analysis_fmt   = fetch_analysis_date()
    qg_status, qg_conditions     = fetch_quality_gate(measures)
    total_issues, by_type, by_sev = fetch_issues()

    report      = build_report(measures, project_name, analysis_iso, analysis_fmt,
                               qg_status, qg_conditions, total_issues, by_type, by_sev)
    output_path = os.path.join(os.getcwd(), OUTPUT_FILE)

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    print_summary(report, output_path)


def wait_for_analysis():
    """Poll CE task queue until analysis is processed."""
    print("\nWaiting for SonarQube to process the analysis", end="", flush=True)
    for _ in range(30):
        time.sleep(2)
        try:
            resp  = fetch(f"/api/ce/component?component={PROJECT_KEY}")
            if not resp.get("queue", []):
                print(" done")
                return True
            print(".", end="", flush=True)
        except Exception:
            print(".", end="", flush=True)
    print(" (timeout - continuing anyway)")
    return False


# ── MAIN ────────────────────────────────────────────────────
if __name__ == "__main__":
    sep = "=" * 52
    print(sep)
    print("  SonarQube Auto Scan + Report Generator")
    print(sep)
    print("\n Starting SonarQube scan for [" + PROJECT_KEY + "] ...\n")

    result = subprocess.run(SCANNER_CMD, cwd=os.getcwd(), shell=True)

    if result.returncode != 0:
        print("\n SonarQube scan FAILED. Report not generated.")
        raise SystemExit(result.returncode)

    print("\n Scan completed successfully!")
    wait_for_analysis()

    try:
        generate_report()
    except Exception as exc:
        print("\n Could not fetch report: " + str(exc))
        print("   Make sure SonarQube is running and credentials are correct.")