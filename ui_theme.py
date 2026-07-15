"""Streamlit 应用的统一企业级视觉样式。"""

import streamlit as st


def apply_global_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink: #18212f;
            --muted: #667085;
            --line: #e6eaf0;
            --surface: #ffffff;
            --canvas: #f6f8fb;
            --brand: #4f46e5;
            --brand-dark: #25235c;
        }

        .stApp { background: var(--canvas); }
        header[data-testid="stHeader"] { background: transparent; }
        [data-testid="stDeployButton"] { display: none; }
        footer { visibility: hidden; }

        .block-container {
            max-width: 1160px;
            padding-top: 2rem;
            padding-bottom: 3.5rem;
        }
        h1, h2, h3 {
            color: var(--ink);
            letter-spacing: -0.025em;
        }
        p, label { color: var(--ink); }

        /* Sidebar */
        [data-testid="stSidebar"] {
            background: #f0f3f8;
            border-right: 1px solid #e1e6ee;
        }
        [data-testid="stSidebar"] .block-container {
            padding: 1.75rem 1.2rem 2rem;
        }
        [data-testid="stSidebar"] [role="radiogroup"] {
            gap: 0.35rem;
        }
        [data-testid="stSidebar"] [role="radiogroup"] label {
            padding: 0.68rem 0.8rem;
            border: 1px solid transparent;
            border-radius: 10px;
            transition: all 0.15s ease;
        }
        [data-testid="stSidebar"] [role="radiogroup"] label:hover {
            background: rgba(255, 255, 255, 0.65);
        }
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
            background: #ffffff;
            border-color: #e0e5ee;
            box-shadow: 0 5px 14px rgba(29, 41, 57, 0.06);
        }
        [data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {
            display: none;
        }
        .sidebar-brand {
            display: flex;
            align-items: center;
            gap: 0.72rem;
            margin-bottom: 1.45rem;
        }
        .brand-mark {
            display: grid;
            width: 42px;
            height: 42px;
            place-items: center;
            color: #ffffff;
            background: var(--brand-dark);
            border-radius: 11px;
            font-weight: 750;
            letter-spacing: -0.04em;
        }
        .sidebar-brand strong {
            display: block;
            color: #202939;
            font-size: 1rem;
            line-height: 1.35;
        }
        .sidebar-brand span {
            display: block;
            color: #7b8495;
            font-size: 0.76rem;
            margin-top: 0.1rem;
        }

        /* Hero */
        .agent-hero {
            position: relative;
            overflow: hidden;
            padding: 2.25rem 2.5rem;
            margin-bottom: 1.35rem;
            color: white;
            background: linear-gradient(120deg, #202044 0%, #2d2a72 62%, #4942b8 100%);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 18px;
            box-shadow: 0 16px 34px rgba(31, 34, 76, 0.16);
        }
        .agent-hero::after {
            content: "";
            position: absolute;
            width: 300px;
            height: 300px;
            right: -90px;
            top: -150px;
            background: rgba(129, 120, 255, 0.24);
            border-radius: 50%;
        }
        .hero-badge {
            position: relative;
            z-index: 1;
            display: inline-block;
            margin-bottom: 0.85rem;
            color: #c9c7ff;
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.13em;
        }
        .agent-hero h1 {
            position: relative;
            z-index: 1;
            margin: 0 0 0.65rem;
            color: #ffffff;
            font-size: 2.15rem;
            line-height: 1.25;
        }
        .agent-hero p {
            position: relative;
            z-index: 1;
            max-width: 730px;
            margin: 0;
            color: #d7d9e8;
            font-size: 1rem;
            line-height: 1.7;
        }
        .hero-tags {
            position: relative;
            z-index: 1;
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            margin-top: 1.15rem;
        }
        .hero-tags span {
            padding: 0.34rem 0.68rem;
            color: #ececff;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 999px;
            font-size: 0.76rem;
        }

        /* Content cards */
        [data-testid="stMetric"] {
            min-height: 104px;
            padding: 1rem 1.15rem;
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 13px;
            box-shadow: 0 4px 14px rgba(29, 41, 57, 0.045);
        }
        [data-testid="stMetricLabel"] { color: var(--muted); }
        [data-testid="stMetricValue"] {
            color: var(--ink);
            font-size: 2rem;
            font-weight: 690;
        }
        .capability-card {
            min-height: 150px;
            padding: 1.2rem 1.25rem;
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 13px;
            box-shadow: 0 4px 14px rgba(29, 41, 57, 0.04);
            transition: transform 0.16s ease, box-shadow 0.16s ease;
        }
        .capability-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 24px rgba(29, 41, 57, 0.08);
        }
        .card-icon {
            display: grid;
            width: 34px;
            height: 34px;
            margin-bottom: 0.8rem;
            place-items: center;
            color: var(--brand);
            background: #eeedff;
            border-radius: 9px;
            font-size: 0.75rem;
            font-weight: 750;
        }
        .capability-card h3 {
            margin: 0 0 0.42rem;
            font-size: 1rem;
        }
        .capability-card p {
            margin: 0;
            color: var(--muted);
            line-height: 1.65;
            font-size: 0.9rem;
        }

        /* Controls */
        .stButton > button {
            min-height: 2.65rem;
            border-color: #d9dfe8;
            border-radius: 9px;
            font-weight: 620;
            box-shadow: none;
        }
        .stButton > button:hover {
            color: var(--brand);
            border-color: #a8a5ee;
        }
        .stButton > button[kind="primary"] {
            color: #ffffff;
            background: var(--brand);
            border: none;
            box-shadow: 0 5px 12px rgba(79, 70, 229, 0.18);
        }
        [data-testid="stFileUploaderDropzone"] {
            background: #fafbfe;
            border: 1px dashed #b8c0cf;
            border-radius: 13px;
        }
        [data-testid="stExpander"], [data-testid="stStatusWidget"] {
            background: var(--surface);
            border-color: var(--line);
            border-radius: 11px;
        }
        [data-testid="stAlert"] { border-radius: 10px; }
        [data-testid="stDataFrame"] {
            overflow: hidden;
            border: 1px solid var(--line);
            border-radius: 11px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
