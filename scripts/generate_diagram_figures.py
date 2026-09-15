import os
import json
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

os.makedirs('figures', exist_ok=True)

with open('scripts/_verified_figure_data.json') as _f:
    _verified = json.load(_f)
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Helvetica', 'Arial']

# -------------------------------------------------------------
# Figure 1: CogniLoop System Architecture & Control Loop
# -------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9.0, 5.0), dpi=300)
ax.set_xlim(0, 10.5)
ax.set_ylim(0, 6.0)
ax.axis('off')

# Color palette: IEEE academic style
SLATE_BOX = '#f1f5f9'
SLATE_BORDER = '#475569'
BLUE_BOX = '#e0f2fe'
BLUE_BORDER = '#0369a1'
AMBER_BOX = '#fef3c7'
AMBER_BORDER = '#b45309'

def draw_academic_box(ax, x, y, w, h, title, subtitle="", color=SLATE_BOX, border=SLATE_BORDER, text_color='#0f172a'):
    rect = patches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08,rounding_size=0.15", 
                                  fc=color, ec=border, lw=1.4)
    ax.add_patch(rect)
    if subtitle:
        ax.text(x + w/2, y + h*0.65, title, fontsize=9.0, fontweight='bold', ha='center', va='center', color=text_color)
        ax.text(x + w/2, y + h*0.28, subtitle, fontsize=7.2, ha='center', va='center', color='#334155')
    else:
        ax.text(x + w/2, y + h/2, title, fontsize=9.0, fontweight='bold', ha='center', va='center', color=text_color)

# Top Layer: Interaction & Web Interface
draw_academic_box(ax, 0.5, 4.5, 2.8, 1.1, "Client Web Application", "HTML5 Video / Telemetry Logger", color=BLUE_BOX, border=BLUE_BORDER)
draw_academic_box(ax, 3.8, 4.5, 2.9, 1.1, "Flask Application Server", "REST Router / PBKDF2 Auth", color=SLATE_BOX, border=SLATE_BORDER)
draw_academic_box(ax, 7.2, 4.5, 2.8, 1.1, "Repository Layer", "POSIX fcntl File-Locked JSON", color=SLATE_BOX, border=SLATE_BORDER)

# Middle Layer: Cognitive & Adaptation Engines
draw_academic_box(ax, 0.5, 2.5, 2.8, 1.2, "K-Means Classifier (K=3)", "Interaction Telemetry Clusters (C0, C1, C2)", color=AMBER_BOX, border=AMBER_BORDER)
draw_academic_box(ax, 3.8, 2.5, 2.9, 1.2, "DC-BKT Cognitive Engine", "Difficulty-Conditioned Guess/Slip Parameters", color=AMBER_BOX, border=AMBER_BORDER)
draw_academic_box(ax, 7.2, 2.5, 2.8, 1.2, "Thompson Sampling Bandit", "Beta-Distributed Reward Optimization", color=AMBER_BOX, border=AMBER_BORDER)

# Bottom Layer: RAG & 3-Tier Generation
draw_academic_box(ax, 0.5, 0.5, 2.8, 1.2, "Vector Retrieval (RAG)", "ChromaDB + all-MiniLM-L6-v2", color=BLUE_BOX, border=BLUE_BORDER)
draw_academic_box(ax, 3.8, 0.5, 6.2, 1.2, "3-Tier Generation & Validation Pipeline", 
                  "Tier 1: Groq Cloud  |  Tier 2: Edge Ollama  |  Tier 3: Static Pool  --> Assessment Validation Layer", 
                  color=SLATE_BOX, border=SLATE_BORDER)

# Data Flow Connectors
arrow_style = dict(arrowstyle="->", lw=1.3, color='#1e293b')
ax.annotate("", xy=(3.8, 5.05), xytext=(3.3, 5.05), arrowprops=arrow_style)
ax.annotate("", xy=(7.2, 5.05), xytext=(6.7, 5.05), arrowprops=arrow_style)

ax.annotate("", xy=(1.9, 3.7), xytext=(1.9, 4.5), arrowprops=arrow_style)
ax.annotate("", xy=(5.25, 3.7), xytext=(5.25, 4.5), arrowprops=arrow_style)

ax.annotate("", xy=(8.6, 1.7), xytext=(8.6, 2.5), arrowprops=arrow_style)
ax.annotate("", xy=(3.8, 1.1), xytext=(3.3, 1.1), arrowprops=arrow_style)
ax.annotate("", xy=(5.25, 2.5), xytext=(5.25, 1.7), arrowprops=dict(arrowstyle="<-", lw=1.3, color='#1e293b'))

plt.tight_layout()
plt.savefig('figures/fig1_architecture.png', bbox_inches='tight')
plt.savefig('figures/fig1_architecture.pdf', bbox_inches='tight')
plt.close()

# -------------------------------------------------------------
# Figure 2: Empirical Normalized Learning Gain (NLG) Comparison
# -------------------------------------------------------------
fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=300)
categories = ['Fast Archetype\n(N=20)', 'Standard Archetype\n(N=20)', 'Slow Archetype\n(N=20)', 'Overall Cohort\n(N=60)']
_f2 = _verified['fig2']
exp_means = [_f2['Fast_experimental_mean'], _f2['Standard_experimental_mean'], _f2['Slow_experimental_mean'], _f2['Overall_experimental_mean']]
exp_errors = [_f2['Fast_experimental_std'], _f2['Standard_experimental_std'], _f2['Slow_experimental_std'], _f2['Overall_experimental_std']]
ctrl_means = [_f2['Fast_control_mean'], _f2['Standard_control_mean'], _f2['Slow_control_mean'], _f2['Overall_control_mean']]
ctrl_errors = [_f2['Fast_control_std'], _f2['Standard_control_std'], _f2['Slow_control_std'], _f2['Overall_control_std']]

x = np.arange(len(categories))
width = 0.34

rects1 = ax.bar(x - width/2, exp_means, width, yerr=exp_errors, label='Experimental Group (CogniLoop Adaptive)', 
                color='#0284c7', capsize=4.5, edgecolor='#0369a1', linewidth=1.2)
rects2 = ax.bar(x + width/2, ctrl_means, width, yerr=ctrl_errors, label='Control Group (Static Video Instruction)', 
                color='#94a3b8', capsize=4.5, edgecolor='#475569', linewidth=1.2)

ax.set_ylabel('Simulated Normalized Learning Gain (NLG)', fontsize=10.0, fontweight='bold', color='#0f172a')
ax.set_title('Simulated Normalized Learning Gain Across Archetypes (Welch\'s t = 3.768, p < 0.001, d = 0.973)', 
             fontsize=10.5, fontweight='bold', pad=12, color='#0f172a')
ax.set_xticks(x)
ax.set_xticklabels(categories, fontsize=9.5, fontweight='bold')
ax.legend(frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=9)
ax.set_ylim(0, 1.15)
ax.grid(axis='y', linestyle='--', alpha=0.45)

for rect in rects1:
    h = rect.get_height()
    ax.annotate(f'{h:.3f}', xy=(rect.get_x() + rect.get_width()/2, h), xytext=(0, 4),
                textcoords="offset points", ha='center', va='bottom', fontsize=8.2, fontweight='bold', color='#0369a1')

for rect in rects2:
    h = rect.get_height()
    ax.annotate(f'{h:.3f}', xy=(rect.get_x() + rect.get_width()/2, h), xytext=(0, 4),
                textcoords="offset points", ha='center', va='bottom', fontsize=8.2, fontweight='bold', color='#475569')

plt.tight_layout()
plt.savefig('figures/fig2_results.png', bbox_inches='tight')
plt.savefig('figures/fig2_results.pdf', bbox_inches='tight')
plt.close()

# -------------------------------------------------------------
# Figure 3: Latent Mastery Convergence Across Steps
# -------------------------------------------------------------
fig, ax = plt.subplots(figsize=(7.5, 4.0), dpi=300)
steps = np.arange(1, 7)

_f3 = _verified['fig3']
fast_exp = _f3['Fast_experimental']
std_exp = _f3['Standard_experimental']
slow_exp = _f3['Slow_experimental']

fast_ctrl = _f3['Fast_control']
std_ctrl = _f3['Standard_control']
slow_ctrl = _f3['Slow_control']

ax.plot(steps, fast_exp, marker='o', lw=2.0, color='#0284c7', label='Fast Archetype (CogniLoop)')
ax.plot(steps, std_exp, marker='s', lw=2.0, color='#0d9488', label='Standard Archetype (CogniLoop)')
ax.plot(steps, slow_exp, marker='^', lw=2.0, color='#d97706', label='Slow Archetype (CogniLoop)')

ax.plot(steps, fast_ctrl, marker='o', lw=1.5, linestyle='--', color='#94a3b8', label='Fast Archetype (Control)')
ax.plot(steps, std_ctrl, marker='s', lw=1.5, linestyle='--', color='#cbd5e1', label='Standard Archetype (Control)')
ax.plot(steps, slow_ctrl, marker='^', lw=1.5, linestyle='--', color='#e2e8f0', label='Slow Archetype (Control)')

ax.axhline(0.85, color='#dc2626', linestyle=':', lw=1.2, label='Mastery Threshold (0.85)')

ax.set_xlabel('Sequential Assessment Iteration (Steps 1 to 6)', fontsize=10, fontweight='bold', color='#0f172a')
ax.set_ylabel('Latent Mastery Probability P(L_n)', fontsize=10, fontweight='bold', color='#0f172a')
ax.set_title('Cognitive State Progression Under DC-BKT and Contextual Thompson Sampling', fontsize=10.5, fontweight='bold', pad=10, color='#0f172a')
ax.set_xticks(steps)
ax.set_ylim(0.1, 1.05)
ax.legend(frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=8.2, loc='lower right', ncol=2)
ax.grid(True, linestyle='--', alpha=0.45)

plt.tight_layout()
plt.savefig('figures/fig3_mastery_convergence.png', bbox_inches='tight')
plt.savefig('figures/fig3_mastery_convergence.pdf', bbox_inches='tight')
plt.close()
print("Updated figures generated successfully.")
