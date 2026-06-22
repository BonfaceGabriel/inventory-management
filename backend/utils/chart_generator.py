import logging
from io import BytesIO
from typing import Dict, List, Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

logger = logging.getLogger(__name__)

COLORS = ['#0891B2', '#F59E0B', '#EF4444', '#10B981', '#8B5CF6', '#EC4899', '#F97316', '#06B6D4']
DARK_TEXT = '#1F2937'
GRID_COLOR = '#E5E7EB'


class ChartGenerator:

    @staticmethod
    def bar_chart(
        data: Dict,
        title: str = '',
        xlabel: str = '',
        ylabel: str = '',
        colors: Optional[List[str]] = None,
        figsize: tuple = (10, 5),
    ) -> BytesIO:
        fig, ax = plt.subplots(figsize=figsize)
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        labels = data.get('labels', [])
        datasets = data.get('datasets', [])
        if not labels or not datasets:
            buf = BytesIO()
            fig.savefig(buf, format='png', dpi=100)
            plt.close(fig)
            buf.seek(0)
            return buf

        n = len(labels)
        bar_width = 0.8 / max(len(datasets), 1)
        x = range(n)
        colors = colors or COLORS

        for i, ds in enumerate(datasets):
            offset = (i - len(datasets) / 2 + 0.5) * bar_width
            ax.bar(
                [xi + offset for xi in x],
                ds['values'],
                width=bar_width * 0.9,
                label=ds.get('label', ''),
                color=colors[i % len(colors)],
                edgecolor='white',
                linewidth=0.5,
            )

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=9, color=DARK_TEXT)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'KES {v:,.0f}'))
        ax.set_xlabel(xlabel, fontsize=10, color=DARK_TEXT)
        ax.set_ylabel(ylabel, fontsize=10, color=DARK_TEXT)
        ax.set_title(title, fontsize=12, fontweight='bold', color=DARK_TEXT, pad=12)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='y', color=GRID_COLOR, linewidth=0.5)
        if datasets and len(datasets) > 1:
            ax.legend(fontsize=9)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def line_chart(
        data: Dict,
        title: str = '',
        xlabel: str = '',
        ylabel: str = '',
        colors: Optional[List[str]] = None,
        figsize: tuple = (10, 5),
    ) -> BytesIO:
        fig, ax = plt.subplots(figsize=figsize)
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        labels = data.get('labels', [])
        datasets = data.get('datasets', [])
        if not labels or not datasets:
            buf = BytesIO()
            fig.savefig(buf, format='png', dpi=100)
            plt.close(fig)
            buf.seek(0)
            return buf

        x = range(len(labels))
        colors = colors or COLORS

        for i, ds in enumerate(datasets):
            ax.plot(
                x, ds['values'],
                marker='o', linewidth=2, markersize=4,
                label=ds.get('label', ''),
                color=colors[i % len(colors)],
            )

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=8, color=DARK_TEXT, rotation=45, ha='right')
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'KES {v:,.0f}'))
        ax.set_xlabel(xlabel, fontsize=10, color=DARK_TEXT)
        ax.set_ylabel(ylabel, fontsize=10, color=DARK_TEXT)
        ax.set_title(title, fontsize=12, fontweight='bold', color=DARK_TEXT, pad=12)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='y', color=GRID_COLOR, linewidth=0.5)
        if datasets and len(datasets) > 1:
            ax.legend(fontsize=9)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf

    @staticmethod
    def pie_chart(
        data: Dict,
        title: str = '',
        colors: Optional[List[str]] = None,
        figsize: tuple = (7, 7),
    ) -> BytesIO:
        fig, ax = plt.subplots(figsize=figsize)
        fig.patch.set_facecolor('white')
        ax.set_facecolor('white')

        labels = data.get('labels', [])
        values = data.get('values', [])
        if not labels or not values:
            buf = BytesIO()
            fig.savefig(buf, format='png', dpi=100)
            plt.close(fig)
            buf.seek(0)
            return buf

        colors = colors or COLORS
        wedges, texts, autotexts = ax.pie(
            values, labels=None, autopct='%1.1f%%',
            startangle=90, colors=colors[:len(labels)],
            textprops={'fontsize': 10, 'color': DARK_TEXT},
        )
        for at in autotexts:
            at.set_fontsize(9)
            at.set_color('white')
            at.set_fontweight('bold')

        legend_labels = [f'{l} — KES {v:,.0f}' for l, v in zip(labels, values)]
        ax.legend(wedges, legend_labels, loc='center left', bbox_to_anchor=(1, 0.5), fontsize=9)
        ax.set_title(title, fontsize=12, fontweight='bold', color=DARK_TEXT, pad=12)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf
