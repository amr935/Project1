# KrishiSahayak

Bilingual (English and Hindi) farm-planning prototype for Bihar and Jharkhand, built with Streamlit.

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

The page opens with saved weather snapshots. Use **Refresh weather** in the sidebar to request a current Open-Meteo forecast. Forecast-based guidance falls back to saved data if the request fails.

## Deploy

Create a GitHub repository, push this source, then deploy `app.py` from [Streamlit Community Cloud](https://share.streamlit.io/). Select Python 3.11 in Advanced settings. The app needs no secrets.

## Current limits

- The crop recommendation model is not included. Its Kaggle source dataset has not been supplied; the crop panel reports this instead of making a recommendation.
- Fertilizer doses, bag weights, MSP rows, and late-blight thresholds marked `VERIFY` need confirmation with the relevant government or Krishi Vigyan Kendra (KVK) source.
- The Evidence panel does not claim historical backtest or field-validation results.
- This is an educational student prototype, not an official agricultural advisory. Follow product labels and local KVK advice.

## Data and support

- Weather: [Open-Meteo](https://open-meteo.com/), attribution under CC BY 4.0.
- Farmer support: Kisan Call Centre, 1800-180-1551.
- The checked-in weather snapshots are public district-level forecasts with no personal farm information.
