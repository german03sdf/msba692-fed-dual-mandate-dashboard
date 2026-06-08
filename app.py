"""
app.py
------
Fed Dual Mandate Dashboard — Interactive Dash Application
MSBA 692 Pipelines to Insights | German Collado Blanco | Week 4

Bloomberg-style dark dashboard that visualizes 70 years of Federal Reserve
economic data to answer: Can the Fed control inflation without destroying jobs?

Data source: FRED API → PostgreSQL (Supabase) → macro_dashboard_snapshot.csv
"""

import os
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash
from dash import dcc, html, Input, Output, callback
from dotenv import load_dotenv

# ── Load Data ─────────────────────────────────────────────────────────────────

load_dotenv()

def load_data():
    """
    Load macro dashboard data.
    Tries PostgreSQL first (live connection), falls back to CSV snapshot.
    This ensures the app works even without a direct database connection.
    """
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(
            f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
            f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'postgres')}",
            connect_args={"sslmode": "require"}
        )
        with engine.connect() as conn:
            df = pd.read_sql(text("SELECT * FROM macro_dashboard ORDER BY obs_date"), conn)
        print("✓ Connected to PostgreSQL (Supabase)")
        return df
    except Exception as e:
        print(f"⚠ PostgreSQL unavailable ({e}), loading from CSV snapshot.")
        df = pd.read_csv("macro_dashboard_snapshot.csv", parse_dates=["obs_date"])
        return df

df = load_data()
df["obs_date"] = pd.to_datetime(df["obs_date"])
df = df.sort_values("obs_date")

# Most recent non-null values for KPI cards
latest_fed   = df["fed_funds_rate"].dropna().iloc[-1]
latest_infl  = df["cpi_yoy"].dropna().iloc[-1]
latest_unemp = df["unemployment"].dropna().iloc[-1]
latest_date  = df["obs_date"].max().strftime("%B %Y")

# ── Bloomberg Color Palette ───────────────────────────────────────────────────

BG_DARK    = "#0a0a0a"
BG_CARD    = "#141414"
BG_CHART   = "#0f0f0f"
GOLD       = "#FFB800"
WHITE      = "#F0F0F0"
GRAY       = "#888888"
RED        = "#FF4444"
BLUE       = "#00AAFF"
GREEN      = "#00CC88"
RECESSION  = "rgba(255, 80, 80, 0.12)"
GRID_COLOR = "#1e1e1e"
BORDER     = "#2a2a2a"

# ── App Layout ────────────────────────────────────────────────────────────────

app = dash.Dash(
    __name__,
    title="Fed Dual Mandate Dashboard",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)

app.layout = html.Div(
    style={"backgroundColor": BG_DARK, "minHeight": "100vh", "fontFamily": "Arial, sans-serif", "padding": "0"},
    children=[

        # ── Header ────────────────────────────────────────────────────────────
        html.Div(
            style={
                "backgroundColor": BG_CARD,
                "borderBottom": f"2px solid {GOLD}",
                "padding": "16px 32px",
                "display": "flex",
                "justifyContent": "space-between",
                "alignItems": "center"
            },
            children=[
                html.Div([
                    html.Span("⬡ ", style={"color": GOLD, "fontSize": "22px"}),
                    html.Span("FED DUAL MANDATE DASHBOARD", style={
                        "color": WHITE, "fontSize": "18px", "fontWeight": "bold", "letterSpacing": "3px"
                    }),
                    html.Span("  |  FEDERAL RESERVE ECONOMIC DATA", style={
                        "color": GRAY, "fontSize": "12px", "letterSpacing": "2px"
                    }),
                ]),
                html.Div([
                    html.Span(f"LAST UPDATED: {latest_date}", style={
                        "color": GOLD, "fontSize": "11px", "letterSpacing": "1px"
                    }),
                    html.Span("  ●  ", style={"color": GREEN}),
                    html.Span("LIVE", style={"color": GREEN, "fontSize": "11px", "letterSpacing": "1px"}),
                ])
            ]
        ),

        # ── Subtitle ──────────────────────────────────────────────────────────
        html.Div(
            "Can the Fed control inflation without destroying jobs?",
            style={
                "color": GRAY, "fontSize": "13px", "textAlign": "center",
                "padding": "10px", "letterSpacing": "1px", "borderBottom": f"1px solid {BORDER}"
            }
        ),

        # ── KPI Cards ─────────────────────────────────────────────────────────
        html.Div(
            style={"display": "flex", "gap": "16px", "padding": "20px 32px 8px"},
            children=[
                # Fed Funds Rate
                html.Div(
                    style={
                        "flex": 1, "backgroundColor": BG_CARD, "borderRadius": "4px",
                        "padding": "16px 24px", "borderLeft": f"3px solid {GOLD}",
                        "border": f"1px solid {BORDER}", "borderLeft": f"3px solid {GOLD}"
                    },
                    children=[
                        html.Div("FED FUNDS RATE", style={"color": GRAY, "fontSize": "10px", "letterSpacing": "2px"}),
                        html.Div(f"{latest_fed:.2f}%", style={"color": GOLD, "fontSize": "32px", "fontWeight": "bold", "margin": "4px 0"}),
                        html.Div("Current target rate", style={"color": GRAY, "fontSize": "11px"}),
                    ]
                ),
                # Inflation
                html.Div(
                    style={
                        "flex": 1, "backgroundColor": BG_CARD, "borderRadius": "4px",
                        "padding": "16px 24px", "border": f"1px solid {BORDER}",
                        "borderLeft": f"3px solid {RED}"
                    },
                    children=[
                        html.Div("CPI INFLATION (YoY)", style={"color": GRAY, "fontSize": "10px", "letterSpacing": "2px"}),
                        html.Div(f"{latest_infl:.2f}%", style={"color": RED, "fontSize": "32px", "fontWeight": "bold", "margin": "4px 0"}),
                        html.Div("Year-over-year change", style={"color": GRAY, "fontSize": "11px"}),
                    ]
                ),
                # Unemployment
                html.Div(
                    style={
                        "flex": 1, "backgroundColor": BG_CARD, "borderRadius": "4px",
                        "padding": "16px 24px", "border": f"1px solid {BORDER}",
                        "borderLeft": f"3px solid {BLUE}"
                    },
                    children=[
                        html.Div("UNEMPLOYMENT RATE", style={"color": GRAY, "fontSize": "10px", "letterSpacing": "2px"}),
                        html.Div(f"{latest_unemp:.1f}%", style={"color": BLUE, "fontSize": "32px", "fontWeight": "bold", "margin": "4px 0"}),
                        html.Div("Current labor market", style={"color": GRAY, "fontSize": "11px"}),
                    ]
                ),
                # Fed Mandate Status
                html.Div(
                    style={
                        "flex": 1, "backgroundColor": BG_CARD, "borderRadius": "4px",
                        "padding": "16px 24px", "border": f"1px solid {BORDER}",
                        "borderLeft": f"3px solid {GREEN}"
                    },
                    children=[
                        html.Div("FED MANDATE TARGET", style={"color": GRAY, "fontSize": "10px", "letterSpacing": "2px"}),
                        html.Div("2.0% / 4.0%", style={"color": GREEN, "fontSize": "32px", "fontWeight": "bold", "margin": "4px 0"}),
                        html.Div("Inflation target / Full employment", style={"color": GRAY, "fontSize": "11px"}),
                    ]
                ),
            ]
        ),

        # ── Date Range Filter ─────────────────────────────────────────────────
        html.Div(
            style={"padding": "8px 32px 4px"},
            children=[
                html.Div("SELECT TIME PERIOD", style={"color": GRAY, "fontSize": "10px", "letterSpacing": "2px", "marginBottom": "8px"}),
                dcc.RangeSlider(
                    id="date-slider",
                    min=df["obs_date"].dt.year.min(),
                    max=df["obs_date"].dt.year.max(),
                    value=[1970, df["obs_date"].dt.year.max()],
                    marks={y: {"label": str(y), "style": {"color": GRAY, "fontSize": "10px"}}
                           for y in range(1954, df["obs_date"].dt.year.max() + 1, 10)},
                    tooltip={"placement": "bottom", "always_visible": False},
                )
            ]
        ),

        # ── Charts ────────────────────────────────────────────────────────────
        html.Div(
            style={"padding": "8px 32px 32px", "display": "flex", "flexDirection": "column", "gap": "16px"},
            children=[
                # Time Series Chart
                html.Div(
                    style={"backgroundColor": BG_CARD, "borderRadius": "4px", "border": f"1px solid {BORDER}", "padding": "16px"},
                    children=[
                        html.Div("MACRO INDICATORS — TIME SERIES", style={
                            "color": WHITE, "fontSize": "12px", "letterSpacing": "2px",
                            "marginBottom": "4px", "fontWeight": "bold"
                        }),
                        html.Div("Fed Funds Rate · CPI Inflation (YoY) · Unemployment Rate · Recession periods shaded", style={
                            "color": GRAY, "fontSize": "10px", "marginBottom": "12px"
                        }),
                        dcc.Graph(id="time-series-chart", config={"displayModeBar": False}, style={"height": "380px"})
                    ]
                ),
                # Phillips Curve
                html.Div(
                    style={"backgroundColor": BG_CARD, "borderRadius": "4px", "border": f"1px solid {BORDER}", "padding": "16px"},
                    children=[
                        html.Div("PHILLIPS CURVE — INFLATION vs UNEMPLOYMENT", style={
                            "color": WHITE, "fontSize": "12px", "letterSpacing": "2px",
                            "marginBottom": "4px", "fontWeight": "bold"
                        }),
                        html.Div("Each point = one month. Color = Fed Funds Rate. The trade-off at the heart of the dual mandate.", style={
                            "color": GRAY, "fontSize": "10px", "marginBottom": "12px"
                        }),
                        dcc.Graph(id="phillips-curve", config={"displayModeBar": False}, style={"height": "380px"})
                    ]
                ),
            ]
        ),

        # ── Footer ────────────────────────────────────────────────────────────
        html.Div(
            style={"borderTop": f"1px solid {BORDER}", "padding": "12px 32px", "display": "flex", "justifyContent": "space-between"},
            children=[
                html.Span("Source: Federal Reserve Economic Data (FRED) — St. Louis Fed", style={"color": GRAY, "fontSize": "10px"}),
                html.Span("MSBA 692 Pipelines to Insights | German Collado Blanco | University of Louisville", style={"color": GRAY, "fontSize": "10px"}),
            ]
        )
    ]
)

# ── Callbacks ─────────────────────────────────────────────────────────────────

def recession_shapes(dff):
    """Generate shaded rectangles for recession periods."""
    shapes = []
    in_recession = False
    start = None
    for _, row in dff.iterrows():
        if row["is_recession"] == 1 and not in_recession:
            in_recession = True
            start = row["obs_date"]
        elif row["is_recession"] != 1 and in_recession:
            in_recession = False
            shapes.append(dict(
                type="rect", xref="x", yref="paper",
                x0=start, x1=row["obs_date"], y0=0, y1=1,
                fillcolor=RECESSION, line=dict(width=0), layer="below"
            ))
    return shapes


@callback(
    Output("time-series-chart", "figure"),
    Output("phillips-curve", "figure"),
    Input("date-slider", "value")
)
def update_charts(year_range):
    dff = df[(df["obs_date"].dt.year >= year_range[0]) & (df["obs_date"].dt.year <= year_range[1])].copy()

    # ── Time Series ───────────────────────────────────────────────────────────
    fig_ts = go.Figure()

    # Recession shading
    for shape in recession_shapes(dff):
        fig_ts.add_shape(shape)

    # Fed Funds Rate
    fig_ts.add_trace(go.Scatter(
        x=dff["obs_date"], y=dff["fed_funds_rate"],
        name="Fed Funds Rate", line=dict(color=GOLD, width=1.5),
        hovertemplate="%{x|%b %Y}<br>Fed Rate: %{y:.2f}%<extra></extra>"
    ))

    # CPI YoY
    fig_ts.add_trace(go.Scatter(
        x=dff["obs_date"], y=dff["cpi_yoy"],
        name="CPI Inflation (YoY)", line=dict(color=RED, width=1.5),
        hovertemplate="%{x|%b %Y}<br>Inflation: %{y:.2f}%<extra></extra>"
    ))

    # Unemployment
    fig_ts.add_trace(go.Scatter(
        x=dff["obs_date"], y=dff["unemployment"],
        name="Unemployment", line=dict(color=BLUE, width=1.5),
        hovertemplate="%{x|%b %Y}<br>Unemployment: %{y:.1f}%<extra></extra>"
    ))

    # Fed 2% inflation target line
    fig_ts.add_hline(y=2, line_dash="dot", line_color=GREEN, line_width=1,
                     annotation_text="2% Target", annotation_font_color=GREEN,
                     annotation_font_size=10)

    fig_ts.update_layout(
        paper_bgcolor=BG_CHART, plot_bgcolor=BG_CHART,
        font=dict(color=GRAY, size=11),
        legend=dict(
            bgcolor="rgba(0,0,0,0)", font=dict(color=WHITE, size=10),
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0
        ),
        xaxis=dict(showgrid=True, gridcolor=GRID_COLOR, linecolor=BORDER, tickfont=dict(color=GRAY)),
        yaxis=dict(showgrid=True, gridcolor=GRID_COLOR, linecolor=BORDER, tickfont=dict(color=GRAY),
                   ticksuffix="%"),
        margin=dict(l=40, r=20, t=40, b=40),
        hovermode="x unified",
    )

    # ── Phillips Curve ────────────────────────────────────────────────────────
    pc_data = dff.dropna(subset=["unemployment", "cpi_yoy", "fed_funds_rate"])

    fig_pc = go.Figure()
    fig_pc.add_trace(go.Scatter(
        x=pc_data["unemployment"],
        y=pc_data["cpi_yoy"],
        mode="markers",
        marker=dict(
            color=pc_data["fed_funds_rate"],
            colorscale=[[0, BLUE], [0.5, GOLD], [1, RED]],
            size=5,
            opacity=0.7,
            colorbar=dict(
                title=dict(text="Fed Rate %", font=dict(color=GRAY, size=10)),
                tickfont=dict(color=GRAY, size=9),
                thickness=12, len=0.8
            )
        ),
        text=pc_data["obs_date"].dt.strftime("%b %Y"),
        hovertemplate="<b>%{text}</b><br>Unemployment: %{x:.1f}%<br>Inflation: %{y:.2f}%<br>Fed Rate: %{marker.color:.2f}%<extra></extra>"
    ))

    # Highlight current point
    latest = dff.dropna(subset=["unemployment", "cpi_yoy"]).iloc[-1]
    fig_pc.add_trace(go.Scatter(
        x=[latest["unemployment"]], y=[latest["cpi_yoy"]],
        mode="markers+text",
        marker=dict(color=WHITE, size=10, symbol="circle", line=dict(color=GOLD, width=2)),
        text=["NOW"], textposition="top right",
        textfont=dict(color=GOLD, size=10),
        showlegend=False,
        hovertemplate=f"<b>Current</b><br>Unemployment: {latest['unemployment']:.1f}%<br>Inflation: {latest['cpi_yoy']:.2f}%<extra></extra>"
    ))

    fig_pc.add_hline(y=2, line_dash="dot", line_color=GREEN, line_width=1,
                     annotation_text="2% Inflation Target", annotation_font_color=GREEN,
                     annotation_font_size=10)

    fig_pc.update_layout(
        paper_bgcolor=BG_CHART, plot_bgcolor=BG_CHART,
        font=dict(color=GRAY, size=11),
        xaxis=dict(
            title=dict(text="Unemployment Rate (%)", font=dict(color=GRAY, size=11)),
            showgrid=True, gridcolor=GRID_COLOR, linecolor=BORDER, tickfont=dict(color=GRAY),
            ticksuffix="%"
        ),
        yaxis=dict(
            title=dict(text="CPI Inflation YoY (%)", font=dict(color=GRAY, size=11)),
            showgrid=True, gridcolor=GRID_COLOR, linecolor=BORDER, tickfont=dict(color=GRAY),
            ticksuffix="%"
        ),
        margin=dict(l=60, r=60, t=20, b=60),
    )

    return fig_ts, fig_pc


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=8050)
