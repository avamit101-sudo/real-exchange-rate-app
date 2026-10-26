"""Real exchange rate explorer using IMF SDMX 3.0 data."""
from __future__ import annotations

import io
from datetime import date
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API_ROOT = "https://api.imf.org/external/sdmx/3.0"
# SDMX 3.0 data query; the series key is supplied as a dimension filter.
DATAFLOW = "IMF.STA,ER,1.0.0"
START_PERIOD = "1976-01"
COUNTRIES = {
    "United States": "USA", "United Kingdom": "GBR", "Euro area": "G163",
    "Japan": "JPN", "Canada": "CAN", "Australia": "AUS", "Switzerland": "CHE",
    "China": "CHN", "India": "IND", "Mexico": "MEX", "Brazil": "BRA",
    "South Africa": "ZAF", "New Zealand": "NZL", "Norway": "NOR", "Sweden": "SWE",
    "Denmark": "DNK", "Korea": "KOR", "Türkiye": "TUR", "Israel": "ISR",
    "France": "FRA", "Germany": "DEU", "Italy": "ITA", "Spain": "ESP",
    "Netherlands": "NLD", "Ireland": "IRL", "Belgium": "BEL", "Austria": "AUT",
    "Portugal": "PRT", "Poland": "POL", "Czechia": "CZE", "Hungary": "HUN",
    "Singapore": "SGP", "Thailand": "THA", "Indonesia": "IDN", "Malaysia": "MYS",
    "Philippines": "PHL", "Saudi Arabia": "SAU", "United Arab Emirates": "ARE",
    "Argentina": "ARG", "Chile": "CHL", "Colombia": "COL", "Peru": "PER",
}

st.set_page_config(page_title="Real Exchange Rate Explorer", page_icon="💱", layout="wide")
st.title("Real Exchange Rate Explorer")
st.caption("Monthly IMF CPI and exchange-rate data. RER = S × CPI₁ / CPI₂; the real index is rebased to 100 over your selected sample.")


def fetch_series(iso: str, indicator: str) -> pd.Series:
    """Fetch one monthly IMF series; tolerate common SDMX response envelopes."""
    key = f"{iso}.{indicator}.M"
    params = {"startPeriod": START_PERIOD, "dimension_at_observation": "AllDimensions"}
    urls = [
        f"{API_ROOT}/data/{DATAFLOW}/{key}",
        f"{API_ROOT}/data/{key}",
    ]
    errors: list[str] = []
    for url in urls:
        try:
            response = requests.get(url, params=params, headers={"Accept": "application/vnd.sdmx.data+json;version=2"}, timeout=45)
            response.raise_for_status()
            payload = response.json()
            parsed = _parse_sdmx(payload)
            if not parsed.empty:
                parsed.name = key
                return parsed
            errors.append(f"{url}: response had no observations")
        except Exception as exc:  # surfaced to user if all endpoints fail
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Could not retrieve " + key + ". " + " | ".join(errors))


def _parse_sdmx(payload: Any) -> pd.Series:
    """Extract time/value observations from typical SDMX-JSON structures."""
    if isinstance(payload, dict):
        # IMF/SDMX JSON may expose observations as a plain list of records.
        for k in ("data", "observations", "value"):
            val = payload.get(k)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                df = pd.DataFrame(val)
                time_col = next((c for c in df if c.lower() in {"time", "period", "time_period", "observation"}), None)
                value_col = next((c for c in df if c.lower() in {"value", "obs_value"}), None)
                if time_col and value_col:
                    return _series_from_pairs(df[time_col], df[value_col])
        # SDMX-JSON compact structure: structure dimensions and series observations.
        data = payload.get("data") or payload.get("dataSets")
        if isinstance(data, list) and data:
            dataset = data[0]
            structure = payload.get("structure", {})
            dims = structure.get("dimensions", {}).get("observation", [])
            time_dim = next((d for d in dims if d.get("id", "").lower() in {"time_period", "time"}), None)
            periods = [v.get("id") for v in time_dim.get("values", [])] if time_dim else []
            series = dataset.get("series", {})
            if isinstance(series, dict):
                for item in series.values():
                    obs = item.get("observations", {})
                    if isinstance(obs, dict):
                        return _series_from_pairs((periods[int(i)] for i in obs if str(i).isdigit() and int(i) < len(periods)), (v[0] for v in obs.values()))
            obs = dataset.get("observations", {})
            if isinstance(obs, dict):
                return _series_from_pairs((periods[int(i)] for i in obs if str(i).isdigit() and int(i) < len(periods)), (v[0] for v in obs.values()))
    return pd.Series(dtype=float)


def _series_from_pairs(periods, values) -> pd.Series:
    rows = []
    for period, value in zip(periods, values):
        try:
            rows.append((pd.Period(str(period), freq="M").to_timestamp(), float(value)))
        except (ValueError, TypeError):
            continue
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series(dict(rows), dtype=float).sort_index()


@st.cache_data(ttl=86400, show_spinner=False)
def load_country(iso: str) -> pd.DataFrame:
    cpi = fetch_series(iso, "CPI").rename("CPI")
    fx = fetch_series(iso, "XDC_USD.PA_RT").rename("LCU_per_USD")
    return pd.concat([cpi, fx], axis=1).sort_index()

with st.sidebar:
    st.header("Countries and sample")
    names = list(COUNTRIES)
    c1 = st.selectbox("Country 1 (base currency)", names, index=names.index("United Kingdom"))
    c2 = st.selectbox("Country 2 (quote currency)", names, index=names.index("United States"))
    chart_mode = st.radio("Chart", ["Real", "Nominal", "Both"], horizontal=True)

if c1 == c2:
    st.warning("Choose two different countries to calculate a bilateral exchange rate.")
    st.stop()

try:
    with st.spinner("Loading monthly IMF CPI and exchange-rate series…"):
        d1, d2 = load_country(COUNTRIES[c1]), load_country(COUNTRIES[c2])
except Exception as exc:
    st.error(f"IMF data could not be loaded: {exc}")
    st.info("The IMF API may be temporarily unavailable or may return a different SDMX response format. Check connectivity and try again.")
    st.stop()

# IMF exchange rates are local currency units per USD. S = currency 2 per currency 1.
# If Country 1 is LCU1/USD and Country 2 is LCU2/USD, S = (LCU2/USD)/(LCU1/USD).
df = pd.concat([d1.add_prefix("C1_"), d2.add_prefix("C2_")], axis=1)
df["S_C2_per_C1"] = df["C2_LCU_per_USD"] / df["C1_LCU_per_USD"]
df["RER"] = df["S_C2_per_C1"] * df["C1_CPI"] / df["C2_CPI"]
valid = df.dropna(subset=["S_C2_per_C1", "RER"]).copy()
if valid.empty:
    st.error("No overlapping valid monthly CPI and exchange-rate observations are available for this pair.")
    st.stop()
min_date, max_date = valid.index.min().date(), valid.index.max().date()
with st.sidebar:
    date_range = st.date_input("Sample months", value=(min_date, max_date), min_value=min_date, max_value=max_date)
if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
    st.info("Select both a start and end month.")
    st.stop()
start, end = map(pd.Timestamp, date_range)
sample = valid.loc[(valid.index >= start) & (valid.index <= end)].copy()
if sample.empty:
    st.error("No valid observations fall within the selected sample.")
    st.stop()
rer_star = sample["RER"].mean()
sample["RER_star"] = rer_star
sample["Real_Index"] = 100 * sample["RER"] / rer_star
sample["Sample_RER_Mean"] = rer_star

st.subheader(f"{c1} / {c2}")
st.caption(f"S(t) is expressed as {c2} currency per 1 {c1}; sample: {sample.index.min():%b %Y}–{sample.index.max():%b %Y}; valid months: {len(sample)}")
left, right = st.columns(2)
left.metric("Sample-average RER*", f"{rer_star:,.6g}")
right.metric("Nominal rate at latest month", f"{sample['S_C2_per_C1'].iloc[-1]:,.6g} {c2} per {c1}")

fig = go.Figure()
if chart_mode in ("Real", "Both"):
    fig.add_trace(go.Scatter(x=sample.index, y=sample["Real_Index"], name="Real index (sample mean = 100)", mode="lines", line={"color": "#2563eb", "width": 2.5}))
if chart_mode == "Nominal":
    fig.add_trace(go.Scatter(x=sample.index, y=sample["S_C2_per_C1"], name=f"Nominal S ({c2} per {c1})", mode="lines", line={"color": "#d97706", "width": 2.5}))
if chart_mode == "Both":
    fig.add_trace(go.Scatter(x=sample.index, y=sample["S_C2_per_C1"], name=f"Nominal S ({c2} per {c1})", mode="lines", line={"color": "#d97706", "width": 2}, yaxis="y2"))
fig.update_layout(template="plotly_white", height=520, hovermode="x unified", margin={"l": 25, "r": 45, "t": 25, "b": 25}, yaxis={"title": "Real index (sample mean = 100)" if chart_mode != "Nominal" else f"Nominal S ({c2} per {c1})"})
if chart_mode == "Both":
    fig.update_layout(yaxis={"title": "Real index (sample mean = 100)"}, yaxis2={"title": f"Nominal S ({c2} per {c1})", "overlaying": "y", "side": "right"})
st.plotly_chart(fig, use_container_width=True)

st.subheader("Selected-sample observations and calculations")
st.caption("CSV contains only selected sample months with both CPIs and both IMF FX observations available. RER* is recomputed for this sample.")
export = sample.reset_index(names="Month")
export["Month"] = export["Month"].dt.strftime("%Y-%m")
export = export[["Month", "C1_CPI", "C2_CPI", "C1_LCU_per_USD", "C2_LCU_per_USD", "S_C2_per_C1", "RER", "RER_star", "Real_Index", "Sample_RER_Mean"]]
st.dataframe(export, use_container_width=True, hide_index=True)
st.download_button("Download selected-sample CSV", export.to_csv(index=False).encode("utf-8"), file_name=f"real_exchange_rate_{COUNTRIES[c1]}_{COUNTRIES[c2]}.csv", mime="text/csv")
with st.expander("Definitions and data notes"):
    st.markdown("""
- **S(t)** = Country 2 currency per unit of Country 1 currency. Because each IMF FX series is local currency units per USD, `S = (C2 local units/USD) / (C1 local units/USD)`.
- **RER(t)** = `S(t) × CPI₁(t) / CPI₂(t)`.
- **RER\*** = arithmetic mean of valid monthly RER observations in the selected sample.
- **Real index(t)** = `100 × RER(t) / RER\*`; its arithmetic sample mean is 100.
- CPI index-base differences can affect level comparisons; this app follows the requested formula without rebasing the input CPIs.
- IMF coverage can be incomplete. Missing CPI or FX months are omitted from calculations and CSV.
""")
