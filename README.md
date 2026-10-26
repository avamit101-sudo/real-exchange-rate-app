# Real Exchange Rate Explorer

A Streamlit app that retrieves monthly consumer price indices and exchange rates from the IMF SDMX 3.0 API, then calculates a bilateral real exchange rate and sample-rebased real index.

## Features

- Country 1 and Country 2 selection, including the Euro area (IMF code `G163`)
- Monthly observations from January 1976 where IMF coverage is available
- `S(t) = Country 2 currency per Country 1 currency`
- `RER(t) = S(t) × CPI₁(t) / CPI₂(t)`
- `RER*` is recalculated as the mean of valid RER months in the selected date range
- Interactive Real, Nominal, or Both charts; Both uses separate vertical axes
- Downloadable CSV with sample observations, inputs, and calculations

## Run locally

Python 3.12 is recommended.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
streamlit run app.py
```

No API key is normally required. The app queries the IMF SDMX 3.0 endpoint. IMF coverage and endpoint availability can vary. Missing months are omitted from calculations.

## Deploy on Streamlit Community Cloud

1. Push `app.py`, `requirements.txt`, and `README.md` to the repository root on the `main` branch.
2. Connect the GitHub repository at [share.streamlit.io](https://share.streamlit.io).
3. Choose `app.py` as the entry point and Python 3.12 in Advanced settings.
4. Deploy. No secrets are required by default.

## Exchange-rate direction

The IMF exchange-rate series are local-currency units per USD. Thus, if `FX₁` and `FX₂` are each local currency units per USD, the required quote `S = currency₂ per currency₁` is `FX₂ / FX₁`. For example, UK as Country 1 and US as Country 2 gives USD per GBP.
