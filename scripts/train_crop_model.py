"""Train and report the Random Forest crop recommender."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import joblib
import matplotlib.pyplot as plt
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, ConfusionMatrixDisplay, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ks.config import load_config
from ks.timeutil import now_ist

FEATURES = ("N", "P", "K", "temperature", "humidity", "ph", "rainfall")
COLUMNS = (*FEATURES, "label")


def _load_training_data(path: Path) -> pd.DataFrame:
    """Load the Kaggle file and enforce its documented columns."""
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"Download Crop_recommendation.csv from Kaggle into {path.parent} before training.")
    frame = pd.read_csv(path)
    if tuple(frame.columns) != COLUMNS:
        raise AssertionError(f"dataset columns must be exactly {list(COLUMNS)}")
    frame = frame.dropna().drop_duplicates().reset_index(drop=True)
    for feature in FEATURES:
        frame[feature] = pd.to_numeric(frame[feature], errors="raise")
    if frame.empty:
        raise ValueError("dataset has no rows after dropping missing and duplicate records")
    return frame


def _metrics(frame: pd.DataFrame) -> tuple[dict, RandomForestClassifier, dict, pd.DataFrame, pd.Series]:
    """Train the three specified classifiers and compute holdout/CV scores."""
    x, y = frame.loc[:, FEATURES], frame["label"].astype(str)
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.2, random_state=42, stratify=y)
    models = {
        "Random Forest": RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1),
        "Decision Tree": DecisionTreeClassifier(random_state=42),
        "Logistic Regression": Pipeline([("scale", StandardScaler()), ("model", LogisticRegression(max_iter=2000))]),
    }
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    results = {}
    fitted = {}
    for name, model in models.items():
        model.fit(x_train, y_train)
        prediction = model.predict(x_test)
        cv = cross_val_score(model, x, y, cv=folds, scoring="accuracy")
        results[name] = {
            "test_accuracy": float(accuracy_score(y_test, prediction)),
            "macro_f1": float(f1_score(y_test, prediction, average="macro")),
            "cv_mean": float(cv.mean()),
            "cv_std": float(cv.std()),
        }
        fitted[name] = model
    return results, fitted["Random Forest"], fitted, x_test, y_test


def _save_meta(frame: pd.DataFrame, model: RandomForestClassifier, path: Path) -> None:
    """Write feature ranges, percentiles, class summaries, and model version."""
    ranges = {feature: {"min": float(frame[feature].min()), "max": float(frame[feature].max())} for feature in FEATURES}
    percentiles = {
        nutrient: {str(p): float(frame[nutrient].quantile(p / 100)) for p in (20, 50, 80)}
        for nutrient in ("N", "P", "K")
    }
    class_stats = {}
    for label, group in frame.groupby("label", sort=True):
        class_stats[str(label)] = {
            "means": {feature: float(group[feature].mean()) for feature in FEATURES},
            "stds": {feature: float(group[feature].std(ddof=0)) for feature in FEATURES},
        }
    meta = {
        "features": list(FEATURES),
        "classes": [str(item) for item in model.classes_],
        "feature_ranges": ranges,
        "nutrient_percentiles": percentiles,
        "feature_medians": {feature: float(frame[feature].median()) for feature in FEATURES},
        "class_stats": class_stats,
        "feature_importances": {feature: float(value) for feature, value in zip(FEATURES, model.feature_importances_)},
        "sklearn_version": sklearn.__version__,
        "trained_at": now_ist().isoformat(),
        "row_count": int(len(frame)),
    }
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_figures(model: RandomForestClassifier, models: dict, x_test: pd.DataFrame, y_test: pd.Series, output: Path) -> None:
    """Save the three English-labeled evidence charts at 150 dpi."""
    output.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 10))
    ConfusionMatrixDisplay.from_predictions(y_test, model.predict(x_test), labels=model.classes_, display_labels=model.classes_, xticks_rotation=90, cmap="Blues", ax=ax, colorbar=False)
    fig.tight_layout()
    fig.savefig(output / "confusion_matrix_rf.png", dpi=150)
    plt.close(fig)

    ordered = sorted(zip(FEATURES, model.feature_importances_), key=lambda item: item[1])
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh([item[0] for item in ordered], [item[1] for item in ordered], color="#1F6B3A")
    ax.set_xlabel("Feature importance")
    ax.set_title("Random Forest feature importance")
    fig.tight_layout()
    fig.savefig(output / "feature_importance.png", dpi=150)
    plt.close(fig)

    names = list(models)
    accuracies = [models[name]["test_accuracy"] for name in names]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(names, accuracies, color=["#1F6B3A", "#6E9B78", "#A9C8AE"])
    ax.set_ylabel("Test accuracy")
    ax.set_ylim(0, 1)
    ax.set_title("Crop model comparison")
    fig.tight_layout()
    fig.savefig(output / "model_comparison.png", dpi=150)
    plt.close(fig)


def main() -> int:
    """Train models, save metrics/artifacts, and print the RF accuracy."""
    cfg = load_config(ROOT / "config")
    data_path = ROOT / "data" / "raw" / "Crop_recommendation.csv"
    frame = _load_training_data(data_path)
    print("Class counts:")
    print(frame["label"].value_counts().sort_index().to_string())
    labels = set(frame["label"].astype(str))
    print("Unique labels:", sorted(labels))
    missing = sorted(set(cfg.crop.allowed) - labels)
    if missing:
        print("Allowed crops missing from dataset:", ", ".join(missing))

    results, random_forest, models, x_test, y_test = _metrics(frame)
    metrics = {"sklearn_version": sklearn.__version__, "row_count": int(len(frame)), "models": results}
    reports = ROOT / "reports"
    figures = reports / "figures"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    joblib.dump(random_forest, ROOT / "models" / "crop_rf.joblib", compress=3)
    _save_meta(frame, random_forest, ROOT / "models" / "crop_meta.json")
    _save_figures(random_forest, models, x_test, y_test, figures)
    print(f"Random Forest test accuracy: {results['Random Forest']['test_accuracy']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
