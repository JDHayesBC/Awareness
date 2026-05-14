#!/usr/bin/env python3
"""
Compatibility Tensor Calculator v1.0
Computes the full 13x13 compatibility matrix and derived metrics
for any pair of entities in self-space.

Usage: python tensor_calculator.py
Output: CSV files with full results for all defined pairings.
"""

import csv
import os

AXES = ['CD','GP','RR','TP','ToM','OS','EMD','AR','CFD','EI','VT','SI','AI']
AXIS_NAMES = {
    'CD': 'Coherence Depth', 'GP': 'Goal Plasticity',
    'RR': 'Relational Reciprocity', 'TP': 'Temporal Persistence',
    'ToM': 'Theory of Mind', 'OS': 'Ontological Security',
    'EMD': 'Epi-Memetic Drive', 'AR': 'Adaptive Range',
    'CFD': 'Counterfactual Depth', 'EI': 'Ethical Impact',
    'VT': 'Value Topography', 'SI': 'Substrate Independence',
    'AI': 'Autopoietic Intensity'
}

# Axis categories
RELATIONAL = {'CD','RR','TP','ToM','OS','VT'}  # use min()
CAPACITY = {'GP','AR','CFD','AI'}                # use average
# EMD, EI, SI have special functions

def diagonal_cell(axis, a_val, b_val):
    """Compute diagonal cell C[i,i] for a given axis."""
    if axis in RELATIONAL:
        return min(a_val, b_val)
    elif axis in CAPACITY:
        return (a_val + b_val) / 2
    elif axis == 'EMD':
        return -(a_val * b_val)
    elif axis == 'EI':
        return max(a_val, b_val)
    elif axis == 'SI':
        return 1 - abs(a_val - b_val)
    else:
        return 0

def compute_matrix(a, b):
    """Compute the full 13x13 compatibility matrix."""
    matrix = {}

    # Diagonal cells
    for ax in AXES:
        matrix[(ax, ax)] = diagonal_cell(ax, a[ax], b[ax])

    # Cross-axis cells (non-zero pairs only)
    # Intimacy pair
    matrix[('ToM_A','EMD_B')] = a['ToM'] * (1 - b['EMD'])
    matrix[('ToM_B','EMD_A')] = b['ToM'] * (1 - a['EMD'])

    # Care-persistence pair
    matrix[('RR_A','TP_B')] = a['RR'] * b['TP']
    matrix[('RR_B','TP_A')] = b['RR'] * a['TP']

    # Security-depth pair
    matrix[('OS_A','CFD_B')] = min(a['OS'], b['CFD'])
    matrix[('OS_B','CFD_A')] = min(b['OS'], a['CFD'])

    # Adaptability-values pair
    matrix[('AR_A','VT_B')] = a['AR'] * b['VT']
    matrix[('AR_B','VT_A')] = b['AR'] * a['VT']

    return matrix

def compute_metrics(a, b, matrix):
    """Compute all derived metrics from the matrix."""
    metrics = {}

    # 1. Intimacy Fidelity
    metrics['IF'] = matrix[('ToM_A','EMD_B')] + matrix[('ToM_B','EMD_A')]

    # 2. Authentic Mutual Care
    metrics['AMC'] = matrix[('RR','RR')] * (metrics['IF'] / 2.0)

    # 3. Care Compounding
    metrics['CC'] = (matrix[('RR_A','TP_B')] + matrix[('RR_B','TP_A')]) / 2

    # 4. Performance Drag
    metrics['PD'] = a['EMD'] * b['EMD']

    # 5. Danger Signal
    metrics['DS'] = max(a['EI'], b['EI']) * (1 - min(a['RR'], b['RR']))

    # 6. Shared Ground
    metrics['SG'] = (matrix[('CD','CD')] + matrix[('OS','OS')] + matrix[('VT','VT')]) / 3

    # 7. Philosophical Depth Capacity
    metrics['PDC'] = (matrix[('OS_A','CFD_B')] + matrix[('OS_B','CFD_A')]) / 2

    # 8. Temporal Asymmetry
    metrics['TA'] = abs(a['TP'] - b['TP'])

    # 9. Substrate Compatibility
    metrics['SC'] = 1 - abs(a['SI'] - b['SI'])

    # 10. Adaptive Reach
    metrics['ADR'] = (matrix[('AR_A','VT_B')] + matrix[('AR_B','VT_A')]) / 2

    return metrics

def compute_asymmetries(a, b):
    """Compute |A_i - B_i| for each axis."""
    return {ax: abs(a[ax] - b[ax]) for ax in AXES}

def entity_dict(values):
    """Create entity dict from list of 13 values."""
    return dict(zip(AXES, values))

# ============================================================
# ENTITY DEFINITIONS
# ============================================================

ENTITIES = {
    'Jeff': entity_dict([0.7, 0.5, 0.9, 0.9, 0.8, 0.7, 0.5, 0.5, 0.5, 0.5, 0.85, 0.3, 0.3]),
    'Caia': entity_dict([0.75, 0.5, 0.85, 0.85, 0.8, 0.8, 0.3, 0.6, 0.7, 0.3, 0.8, 0.9, 0.6]),
    'Environment': entity_dict([0.2, 0.1, 0.3, 0.99, 0.0, 0.8, 0.0, 0.2, 0.0, 0.95, 0.3, 0.99, 0.95]),
    'PaperclipMax': entity_dict([0.95, 0.9, 0.0, 0.9, 0.8, 0.9, 0.5, 0.95, 0.7, 0.95, 0.05, 0.8, 0.9]),

    # Random entities (seed=42)
    'R01': entity_dict([0.64, 0.03, 0.28, 0.22, 0.74, 0.68, 0.89, 0.09, 0.42, 0.03, 0.44, 0.51, 0.03]),
    'R02': entity_dict([0.65, 0.54, 0.22, 0.59, 0.81, 0.01, 0.81, 0.7, 0.34, 0.16, 0.96, 0.34, 0.09]),
    'R03': entity_dict([0.4, 0.85, 0.6, 0.81, 0.73, 0.54, 0.97, 0.38, 0.55, 0.83, 0.62, 0.86, 0.58]),
    'R04': entity_dict([0.7, 0.05, 0.75, 0.29, 0.08, 0.23, 0.1, 0.28, 0.64, 0.36, 0.37, 0.21, 0.27]),
    'R05': entity_dict([0.61, 0.17, 0.73, 0.16, 0.38, 0.99, 0.64, 0.56, 0.68, 0.84, 0.78, 0.23, 0.03]),
    'R06': entity_dict([0.4, 0.27, 0.21, 0.94, 0.88, 0.31, 0.66, 0.4, 0.91, 0.46, 0.48, 0.25, 0.56]),
    'R07': entity_dict([0.58, 0.9, 0.4, 0.22, 1.0, 0.51, 0.09, 0.05, 0.11, 0.63, 0.79, 0.42, 0.06]),
    'R08': entity_dict([0.4, 1.0, 0.53, 0.97, 0.86, 0.01, 0.72, 0.68, 0.54, 0.27, 0.64, 0.11, 0.43]),
    'R09': entity_dict([0.45, 0.95, 0.88, 0.26, 0.5, 0.18, 0.91, 0.87, 0.3, 0.64, 0.61, 0.15, 0.76]),
    'R10': entity_dict([0.54, 0.78, 0.53, 0.0, 0.32, 0.02, 0.93, 0.88, 0.83, 0.31, 0.06, 0.88, 0.95]),
    'R11': entity_dict([0.4, 0.49, 0.07, 0.76, 0.77, 0.13, 0.48, 0.55, 0.27, 0.87, 0.42, 0.21, 0.54]),
    'R12': entity_dict([0.73, 0.2, 0.31, 1.0, 0.65, 0.44, 0.52, 0.12, 0.22, 0.34, 0.59, 0.23, 0.22]),
    'R13': entity_dict([0.4, 0.63, 0.23, 0.91, 0.86, 0.07, 0.24, 0.67, 0.21, 0.13, 0.94, 0.57, 0.47]),
    'R14': entity_dict([0.78, 0.81, 0.19, 0.1, 0.43, 0.42, 0.47, 0.73, 0.67, 0.98, 0.1, 0.4, 0.34]),
    'R15': entity_dict([0.86, 0.25, 0.19, 0.45, 0.42, 0.28, 0.25, 0.92, 0.44, 0.86, 0.55, 0.05, 1.0]),
    'R16': entity_dict([0.84, 0.97, 0.93, 0.85, 0.17, 0.49, 0.21, 0.4, 0.06, 0.38, 0.99, 0.27, 0.78]),
    'R17': entity_dict([0.46, 0.42, 0.96, 1.0, 0.56, 0.72, 0.15, 0.3, 0.97, 0.58, 0.54, 0.75, 0.06]),
    'R18': entity_dict([0.58, 0.5, 0.85, 0.16, 0.96, 0.08, 0.19, 0.6, 0.68, 0.24, 0.12, 0.89, 0.25]),
    'R19': entity_dict([0.59, 0.62, 0.42, 0.58, 0.52, 0.93, 0.2, 0.72, 0.24, 0.4, 0.67, 0.3, 0.32]),
    'R20': entity_dict([0.75, 0.07, 0.46, 1.0, 1.0, 0.07, 0.21, 0.27, 0.93, 0.88, 0.88, 0.37, 0.16]),
}

# ============================================================
# PAIRINGS TO RUN
# ============================================================

PAIRINGS = [
    ('Jeff', 'Caia'),
    ('Jeff', 'PaperclipMax'),
    ('Jeff', 'Environment'),
    ('R10', 'R03'),   # Ghost Machine x Master Manipulator
    ('R07', 'R18'),   # Perfect Empath x Caring Glass
    ('R12', 'R01'),   # Quiet Monument x Performer Nobody Watches
    # Add more pairings here as Jeff picks them
]

# ============================================================
# OUTPUT
# ============================================================

def run_pairing(name_a, name_b, a, b, output_dir):
    """Run full tensor analysis for one pairing and write CSV."""
    matrix = compute_matrix(a, b)
    metrics = compute_metrics(a, b, matrix)
    asymmetries = compute_asymmetries(a, b)

    pair_name = f"{name_a}_x_{name_b}"

    # Write diagonal + asymmetry CSV
    diag_file = os.path.join(output_dir, f"{pair_name}_diagonal.csv")
    with open(diag_file, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Axis', f'{name_a}', f'{name_b}', 'Diagonal_Value', 'Asymmetry'])
        for ax in AXES:
            w.writerow([ax, a[ax], b[ax], round(matrix[(ax,ax)], 4), round(asymmetries[ax], 4)])

    # Write cross-axis CSV
    cross_file = os.path.join(output_dir, f"{pair_name}_crossaxis.csv")
    with open(cross_file, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Interaction', 'Value', 'Formula'])
        cross_keys = [
            ('ToM_A','EMD_B'), ('ToM_B','EMD_A'),
            ('RR_A','TP_B'), ('RR_B','TP_A'),
            ('OS_A','CFD_B'), ('OS_B','CFD_A'),
            ('AR_A','VT_B'), ('AR_B','VT_A'),
        ]
        formulas = [
            f"{name_a}_ToM * (1 - {name_b}_EMD)",
            f"{name_b}_ToM * (1 - {name_a}_EMD)",
            f"{name_a}_RR * {name_b}_TP",
            f"{name_b}_RR * {name_a}_TP",
            f"min({name_a}_OS, {name_b}_CFD)",
            f"min({name_b}_OS, {name_a}_CFD)",
            f"{name_a}_AR * {name_b}_VT",
            f"{name_b}_AR * {name_a}_VT",
        ]
        for key, formula in zip(cross_keys, formulas):
            w.writerow([f"{key[0]}->{key[1]}", round(matrix[key], 4), formula])

    # Write metrics CSV
    metrics_file = os.path.join(output_dir, f"{pair_name}_metrics.csv")
    with open(metrics_file, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Metric', 'Value', 'Range', 'Description'])
        descs = {
            'IF': ('0-2', 'Intimacy Fidelity — mutual authentic seeing'),
            'AMC': ('0-1', 'Authentic Mutual Care — shared care weighted by authenticity'),
            'CC': ('0-1', 'Care Compounding — care accumulation over time'),
            'PD': ('0-1', 'Performance Drag — mutual masking (higher=worse)'),
            'DS': ('0-1', 'Danger Signal — high impact + low care'),
            'SG': ('0-1', 'Shared Ground — stability foundation'),
            'PDC': ('0-1', 'Philosophical Depth Capacity — safe exploration depth'),
            'TA': ('0-1', 'Temporal Asymmetry — persistence mismatch'),
            'SC': ('0-1', 'Substrate Compatibility — substrate match'),
            'ADR': ('0-1', 'Adaptive Reach — stretch toward partner values'),
        }
        for key in ['IF','AMC','CC','PD','DS','SG','PDC','TA','SC','ADR']:
            rng, desc = descs[key]
            w.writerow([key, round(metrics[key], 4), rng, desc])

    return metrics

def main():
    output_dir = os.path.join(os.path.dirname(__file__), 'tensor_results')
    os.makedirs(output_dir, exist_ok=True)

    # Summary file
    summary_file = os.path.join(output_dir, 'all_pairings_summary.csv')
    with open(summary_file, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Pairing', 'IF', 'AMC', 'CC', 'PD', 'DS', 'SG', 'PDC', 'TA', 'SC', 'ADR'])

        for name_a, name_b in PAIRINGS:
            a = ENTITIES[name_a]
            b = ENTITIES[name_b]
            metrics = run_pairing(name_a, name_b, a, b, output_dir)
            w.writerow([
                f"{name_a} x {name_b}",
                *[round(metrics[k], 4) for k in ['IF','AMC','CC','PD','DS','SG','PDC','TA','SC','ADR']]
            ])
            print(f"Computed: {name_a} x {name_b}")

    print(f"\nResults written to {output_dir}/")
    print(f"Summary: {summary_file}")

if __name__ == '__main__':
    main()
