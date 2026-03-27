import logging
from datetime import date
from io import BytesIO

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)

COLORS = [
    "#4FC3F7",
    "#81C784",
    "#FFB74D",
    "#E57373",
    "#BA68C8",
    "#4DD0E1",
    "#FFD54F",
    "#F06292",
    "#AED581",
    "#90A4AE",
]
ACCENT = "#4FC3F7"
BG_COLOR = "#1E1E1E"
TEXT_COLOR = "#E0E0E0"
GRID_COLOR = "#333333"


def _setup_style():
    plt.rcParams.update(
        {
            "figure.facecolor": BG_COLOR,
            "axes.facecolor": BG_COLOR,
            "axes.edgecolor": GRID_COLOR,
            "axes.labelcolor": TEXT_COLOR,
            "text.color": TEXT_COLOR,
            "xtick.color": TEXT_COLOR,
            "ytick.color": TEXT_COLOR,
            "grid.color": GRID_COLOR,
            "grid.alpha": 0.3,
            "font.size": 12,
        }
    )


def _render_to_buffer(fig) -> BytesIO:
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150, facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_category_pie(categories: dict[str, float]) -> BytesIO | None:
    if len(categories) < 2:
        return None

    total = sum(categories.values())
    if total <= 0:
        return None

    # Group small categories into "Other"
    threshold = total * 0.03
    main = {}
    other = 0.0
    for cat, amount in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        if amount >= threshold:
            main[cat] = amount
        else:
            other += amount
    if other > 0:
        main["Other"] = other

    _setup_style()
    fig, ax = plt.subplots(figsize=(8, 5))

    labels = list(main.keys())
    values = list(main.values())
    colors = COLORS[: len(labels)]

    wedges, texts, autotexts = ax.pie(
        values,
        labels=None,
        autopct=lambda p: f"${p * total / 100:,.0f}" if p > 5 else "",
        colors=colors,
        startangle=90,
        pctdistance=0.75,
        wedgeprops={"width": 0.5, "edgecolor": BG_COLOR, "linewidth": 2},
    )

    for t in autotexts:
        t.set_fontsize(10)
        t.set_color(TEXT_COLOR)

    ax.legend(
        labels,
        loc="center left",
        bbox_to_anchor=(1.0, 0.5),
        fontsize=10,
        frameon=False,
    )

    ax.set_title("Spending by Category", fontsize=14, fontweight="bold", pad=15)

    return _render_to_buffer(fig)


def generate_monthly_trend(monthly_data: dict[str, float]) -> BytesIO | None:
    if len(monthly_data) < 2:
        return None

    _setup_style()
    fig, ax = plt.subplots(figsize=(8, 5))

    labels = list(monthly_data.keys())
    values = list(monthly_data.values())

    # Highlight the last month (current)
    colors = [GRID_COLOR] * len(values)
    colors[-1] = ACCENT

    bars = ax.bar(labels, values, color=colors, width=0.6, edgecolor="none")

    # Value labels on top
    for bar, val in zip(bars, values):
        if val > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(values) * 0.02,
                f"${val:,.0f}",
                ha="center",
                va="bottom",
                fontsize=10,
                color=TEXT_COLOR,
            )

    ax.set_title("Monthly Spending", fontsize=14, fontweight="bold", pad=15)
    ax.set_ylabel("SGD")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)

    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()

    return _render_to_buffer(fig)


def generate_daily_spending(daily_data: dict[date, float], period_label: str) -> BytesIO | None:
    if len(daily_data) < 2:
        return None

    _setup_style()
    fig, ax = plt.subplots(figsize=(8, 5))

    sorted_dates = sorted(daily_data.keys())
    values = [daily_data[d] for d in sorted_dates]

    # Format x labels based on range
    if len(sorted_dates) <= 7:
        labels = [d.strftime("%a") for d in sorted_dates]
    else:
        labels = [d.strftime("%d %b") for d in sorted_dates]

    ax.plot(labels, values, color=ACCENT, linewidth=2, marker="o", markersize=5)
    ax.fill_between(labels, values, alpha=0.15, color=ACCENT)

    ax.set_title(f"Daily Spending — {period_label}", fontsize=14, fontweight="bold", pad=15)
    ax.set_ylabel("SGD")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)

    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()

    return _render_to_buffer(fig)
