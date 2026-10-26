"""Real exchange rate explorer using IMF SDMX 3.0 data."""
from __future__ import annotations

import io

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API_ROOT = "https://api.imf.org/external/sdmx/3.0"
# SDMX 3.0 dataflow IDs and series keys as documented by the IMF.
DATAFLOWS = {"CPI": "CPI", "XDC_USD.PA_RT": "ER"}
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
    """Fetch one monthly IMF series using the SDMX 3.0 dataflow URL."""
    if indicator == "CPI":
        # IMF CPI dimensions: country, index, COICOP, transformation, frequency.
        key = f"{iso}.CPI._T.IX.M"
        dataflow = DATAFLOWS["CPI"]
    elif indicator == "XDC_USD.PA_RT":
        key = f"{iso}.XDC_USD.PA_RT.M"
        dataflow = DATAFLOWS[indicator]
    else:
        raise ValueError(f"Unsupported IMF indicator: {indicator}")

    url = f"{API_ROOT}/data/dataflow/IMF.STA/{dataflow}/~/{key}"
    params = {"c[TIME_PERIOD]": "ge:1976-M01"}
    response = requests.get(url, params=params, headers={"Accept": "text/csv"}, timeout=60)
    response.raise_for_status()
    try:
        observations = pd.read_csv(io.StringIO(response.text))
    except Exception as exc:
        raise RuntimeError(f"IMF returned an unreadable CSV for {key}: {exc}") from exc
    if not {"TIME_PERIOD", "OBS_VALUE"}.issubset(observations.columns):
        raise RuntimeError(f"IMF response for {key} lacked TIME_PERIOD/OBS_VALUE columns")
    periods = observations["TIME_PERIOD"].astype(str).str.replace(r"-M(\d+)$", r"-\1", regex=True)
    index = pd.PeriodIndex(periods, freq="M").to_timestamp()
    values = pd.to_numeric(observations["OBS_VALUE"], errors="coerce")
    series = pd.Series(values.to_numpy(), index=index, dtype=float).dropna().sort_index()
    series.name = key
    return series


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
