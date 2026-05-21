"""
analyzer.py — Статистика, инсайты и графики
"""

import io
import logging
from statistics import mean, stdev
from typing import Optional

import db_handler as db

logger = logging.getLogger(__name__)

# Попытка импортировать matplotlib; если нет — графики недоступны
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from datetime import datetime
    MATPLOTLIB_OK = True
except ImportError:
    MATPLOTLIB_OK = False
    logger.warning("matplotlib не установлен — графики недоступны")


MOOD_LABELS = {1: "😞 Ужасно", 2: "😐 Плохо", 3: "🙂 Нормально",
               4: "😊 Хорошо", 5: "🤩 Отлично"}


def _fmt(value: float, unit: str = "") -> str:
    return f"{value:.1f}{unit}"


# ──────────────────────────────────────────────
#  Недельная сводка
# ──────────────────────────────────────────────
def weekly_summary(user_id: int) -> str:
    rows = db.get_entries_for_period(user_id, 7)
    return _build_summary(rows, "📅 Статистика за последние 7 дней")


# ──────────────────────────────────────────────
#  Месячная сводка
# ──────────────────────────────────────────────
def monthly_summary(user_id: int) -> str:
    rows = db.get_entries_for_period(user_id, 30)
    return _build_summary(rows, "🗓 Статистика за последние 30 дней")


def _build_summary(rows: list[dict], title: str) -> str:
    if not rows:
        return f"{title}\n\n⚠️ Данных пока нет. Начни с /add"

    moods  = [r["mood"]        for r in rows]
    study  = [r["study_hours"] for r in rows]
    sleep  = [r["sleep_hours"] for r in rows]
    n      = len(rows)

    avg_mood  = mean(moods)
    avg_study = mean(study)
    avg_sleep = mean(sleep)

    best_day  = max(rows, key=lambda r: r["mood"])
    worst_day = min(rows, key=lambda r: r["mood"])

    lines = [
        f"<b>{title}</b>  ({n} записей)\n",
        f"  🌤 Среднее настроение: <b>{_fmt(avg_mood)}/5</b>  {_mood_bar(avg_mood)}",
        f"  📚 Среднее время учёбы: <b>{_fmt(avg_study)} ч</b>",
        f"  😴 Среднее время сна: <b>{_fmt(avg_sleep)} ч</b>\n",
        f"  🏆 Лучший день: <b>{best_day['entry_date']}</b> — настроение {best_day['mood']}/5",
        f"  📉 Худший день: <b>{worst_day['entry_date']}</b> — настроение {worst_day['mood']}/5",
    ]

    if n >= 3:
        mood_sd = stdev(moods)
        lines.append(f"\n  📊 Разброс настроения: <b>{_fmt(mood_sd)}</b> (чем меньше, тем стабильнее)")

    return "\n".join(lines)


def _mood_bar(avg: float) -> str:
    filled = round(avg)
    return "⬛" * filled + "⬜" * (5 - filled)


# ──────────────────────────────────────────────
#  Инсайты (корреляции)
# ──────────────────────────────────────────────
def insights(user_id: int) -> str:
    rows = db.get_entries_for_period(user_id, 30)
    if len(rows) < 5:
        return "🔍 <b>Инсайты</b>\n\n⚠️ Нужно минимум 5 записей для анализа. Продолжай заполнять ежедневник!"

    lines = ["🔍 <b>Твои персональные инсайты</b>\n"]

    # Инсайт 1: сон vs настроение
    sleep_insight = _correlation_insight(
        rows, "sleep_hours", "mood",
        low_threshold=6.5, high_threshold=7.5,
        low_label="< 6.5 ч", high_label="> 7.5 ч",
        metric_name="Сон"
    )
    lines.append(f"😴 <b>Сон и настроение</b>\n{sleep_insight}\n")

    # Инсайт 2: учёба vs настроение
    study_insight = _correlation_insight(
        rows, "study_hours", "mood",
        low_threshold=3.0, high_threshold=5.0,
        low_label="< 3 ч", high_label="> 5 ч",
        metric_name="Учёба"
    )
    lines.append(f"📚 <b>Учёба и настроение</b>\n{study_insight}\n")

    # Инсайт 3: лучшие дни недели
    weekday_insight = _weekday_insight(rows)
    lines.append(f"📆 <b>Лучшие дни недели</b>\n{weekday_insight}")

    return "\n".join(lines)


def _correlation_insight(rows, x_key, y_key,
                          low_threshold, high_threshold,
                          low_label, high_label, metric_name) -> str:
    low  = [r[y_key] for r in rows if r[x_key] <  low_threshold]
    high = [r[y_key] for r in rows if r[x_key] >= high_threshold]

    if not low or not high:
        return "  Недостаточно данных для сравнения."

    avg_low  = mean(low)
    avg_high = mean(high)
    diff     = avg_high - avg_low

    if abs(diff) < 0.15:
        return f"  Похоже, {metric_name.lower()} мало влияет на {y_key}. Нужно больше данных."
    elif diff > 0:
        return (f"  При {metric_name.lower()} {high_label} твоё настроение <b>выше</b> "
                f"на {_fmt(diff)} балла ({_fmt(avg_high)} vs {_fmt(avg_low)}) ✅")
    else:
        return (f"  При {metric_name.lower()} {low_label} твоё настроение <b>выше</b> "
                f"на {_fmt(-diff)} балла ({_fmt(avg_low)} vs {_fmt(avg_high)}) ⚠️")


def _weekday_insight(rows) -> str:
    weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    buckets: dict[int, list] = {i: [] for i in range(7)}
    for r in rows:
        try:
            from datetime import date
            d = date.fromisoformat(r["entry_date"])
            buckets[d.weekday()].append(r["mood"])
        except Exception:
            pass

    avgs = {k: mean(v) for k, v in buckets.items() if v}
    if not avgs:
        return "  Нет данных."

    best_wd  = max(avgs, key=avgs.get)
    worst_wd = min(avgs, key=avgs.get)

    return (f"  🥇 Лучший день: <b>{weekday_names[best_wd]}</b> (среднее {_fmt(avgs[best_wd])}/5)\n"
            f"  😔 Сложнее всего: <b>{weekday_names[worst_wd]}</b> (среднее {_fmt(avgs[worst_wd])}/5)")


# ──────────────────────────────────────────────
#  График настроения
# ──────────────────────────────────────────────
def mood_chart(user_id: int) -> Optional[io.BytesIO]:
    if not MATPLOTLIB_OK:
        return None

    rows = db.get_entries_for_period(user_id, 30)
    if len(rows) < 2:
        return None

    dates = [datetime.strptime(r["entry_date"], "%Y-%m-%d") for r in rows]
    moods = [r["mood"]        for r in rows]
    sleep = [r["sleep_hours"] for r in rows]
    study = [r["study_hours"] for r in rows]

    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    fig.patch.set_facecolor("#1a1a2e")
    colors = ["#e94560", "#0f3460", "#533483"]
    titles = ["Настроение (1–5)", "Сон (ч)", "Учёба/работа (ч)"]
    data_sets = [moods, sleep, study]
    y_limits = [(0.5, 5.5), (0, 12), (0, 12)]

    for ax, color, title, data, ylim in zip(axes, colors, titles, data_sets, y_limits):
        ax.set_facecolor("#16213e")
        ax.plot(dates, data, color=color, linewidth=2, marker="o",
                markersize=5, markerfacecolor="white")
        ax.fill_between(dates, data, alpha=0.15, color=color)
        ax.set_ylim(*ylim)
        ax.set_ylabel(title, color="white", fontsize=9)
        ax.tick_params(colors="white", labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#444")
        ax.yaxis.set_label_coords(-0.08, 0.5)
        ax.grid(axis="y", linestyle="--", alpha=0.3, color="#555")

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    axes[-1].xaxis.set_major_locator(mdates.DayLocator(interval=3))
    axes[-1].tick_params(axis="x", colors="white", rotation=30)

    fig.suptitle("Твой дневник за последние 30 дней", color="white",
                 fontsize=13, fontweight="bold", y=0.98)
    plt.tight_layout(rect=[0, 0, 1, 0.97])

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf