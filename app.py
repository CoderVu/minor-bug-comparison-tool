import os
import pandas as pd
import tempfile
import html
import json
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'test-comparison-app-secret-key'
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'csv'}
TEMP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp')
os.makedirs(TEMP_FOLDER, exist_ok=True)

# Define display names for the result structure
DISPLAY_NAMES = {
    'file1_name': 'File 1',
    'file2_name': 'File 2',
    'failed_file1_only': 'Cases Failed in {file1_name}',
    'failed_file2_only': 'Cases Failed in {file2_name}',

    'passed_file1_only': 'Cases Passed only in {file1_name}',
    'passed_file2_only': 'Cases Passed only in {file2_name}',
    'passed_both': 'Cases Passed in both files',
    'minor_file1_only': 'Minor Bug only in {file1_name}',
    'minor_file2_only': 'Minor Bug only in {file2_name}',
    'minor_both': 'Minor Bug in both files',
    'minor_all': 'All Minor Bugs',
    'minor_by_plan': 'Minor Bugs By Test Plan',
    'failed_by_plan': 'Failed Cases By Test Plan'  # Added this line
}

def compare_test_results_as_tables(file1_path, file2_path, custom_label1=None, custom_label2=None):
    """Compare test results and return dataframes for display in tables"""
    # Create short names for files (up to 10 chars)
    file1_name = os.path.basename(file1_path).split('.')[0]
    file2_name = os.path.basename(file2_path).split('.')[0]

    # Use custom labels if provided
    if custom_label1 and custom_label1.strip():
        display_file1_name = custom_label1.strip()
    else:
        # Create shortened names for display
        display_file1_name = file1_name[:15] if len(file1_name) > 15 else file1_name

    if custom_label2 and custom_label2.strip():
        display_file2_name = custom_label2.strip()
    else:
        display_file2_name = file2_name[:15] if len(file2_name) > 15 else file2_name

    # Load data from files - print column names for debugging
    # print(f"Reading file 1: {file1_path}")
    df1 = pd.read_csv(file1_path, encoding='utf-8', on_bad_lines='skip')
    # print(f"File 1 columns: {df1.columns.tolist()}")

    # print(f"Reading file 2: {file2_path}")
    df2 = pd.read_csv(file2_path, encoding='utf-8', on_bad_lines='skip')
    # print(f"File 2 columns: {df2.columns.tolist()}")

    # Find important columns in dataframes with case-insensitive matching
    case_id_col1 = find_case_id_column(df1)
    status_col1 = find_status_column(df1)
    title_col1 = find_title_column(df1)
    comment_col1 = find_comment_column(df1)
    tested_by_col1 = find_tested_by_column(df1)
    plan_col1 = find_plan_column(df1)

    case_id_col2 = find_case_id_column(df2)
    status_col2 = find_status_column(df2)
    title_col2 = find_title_column(df2)
    comment_col2 = find_comment_column(df2)
    tested_by_col2 = find_tested_by_column(df2)
    plan_col2 = find_plan_column(df2)

    # Verify required columns exist
    if not case_id_col1 or not status_col1:
        raise ValueError(f"Could not find 'Case ID' and 'Status' columns in first file. Available columns: {df1.columns.tolist()}")
    if not case_id_col2 or not status_col2:
        raise ValueError(f"Could not find 'Case ID' and 'Status' columns in second file. Available columns: {df2.columns.tolist()}")
    if not title_col1:
        raise ValueError(f"Could not find 'Title' column in first file. Available columns: {df1.columns.tolist()}")
    if not title_col2:
        raise ValueError(f"Could not find 'Title' column in second file. Available columns: {df2.columns.tolist()}")

    # Define columns we care about - only include those that exist
    columns1 = [case_id_col1]
    columns2 = [case_id_col2]

    # Keep original column names
    column_map1 = {col: col for col in df1.columns}
    column_map2 = {col: col for col in df2.columns}

    # Add important columns first
    if title_col1:
        columns1.append(title_col1)
    if title_col2:
        columns2.append(title_col2)

    if comment_col1:
        columns1.append(comment_col1)
    else:
        df1["Comment"] = ""
        comment_col1 = "Comment"
        columns1.append(comment_col1)
        column_map1[comment_col1] = "Comment"

    if comment_col2:
        columns2.append(comment_col2)
    else:
        df2["Comment"] = ""
        comment_col2 = "Comment"
        columns2.append(comment_col2)
        column_map2[comment_col2] = "Comment"

    # Add Plan column if it exists
    if plan_col1:
        columns1.append(plan_col1)
    if plan_col2:
        columns2.append(plan_col2)

    # Add Status column
    columns1.append(status_col1)
    columns2.append(status_col2)

    # Add Tested By if available
    if tested_by_col1:
        columns1.append(tested_by_col1)
    if tested_by_col2:
        columns2.append(tested_by_col2)

    # Handle NaN values in the Comment column
    if comment_col1:
        df1[comment_col1] = df1[comment_col1].fillna("")
    if comment_col2:
        df2[comment_col2] = df2[comment_col2].fillna("")

    # Handle NaN values in the Plan column if it exists
    if plan_col1:
        df1[plan_col1] = df1[plan_col1].fillna("No Plan")
    if plan_col2:
        df2[plan_col2] = df2[plan_col2].fillna("No Plan")

    # Get passed and failed tests
    df1_passed = df1[df1[status_col1].str.lower() == "passed"]
    df1_failed = df1[df1[status_col1].str.lower() == "failed"]
    df2_passed = df2[df2[status_col2].str.lower() == "passed"]
    df2_failed = df2[df2[status_col2].str.lower() == "failed"]

    # Create sets of Case IDs
    df1_fail_ids = set(df1_failed[case_id_col1])
    df2_fail_ids = set(df2_failed[case_id_col2])
    df1_pass_ids = set(df1_passed[case_id_col1])
    df2_pass_ids = set(df2_passed[case_id_col2])

    # Compare failed cases
    fail_in_file1_only_ids = df1_fail_ids - df2_fail_ids
    fail_in_file2_only_ids = df2_fail_ids - df1_fail_ids
    fail_in_both_ids = df1_fail_ids & df2_fail_ids

    # Compare passed cases
    pass_in_file1_only_ids = df1_pass_ids - df2_pass_ids
    pass_in_file2_only_ids = df2_pass_ids - df1_pass_ids
    pass_in_both_ids = df1_pass_ids & df2_pass_ids

    # Find minor issues - looking for any variation of 'minor' in comments
    # Use a more flexible pattern to match variations like 'minor', 'Minor', 'MINOR', etc.
    minor_pattern = r"(?i)\bminor\b"  # (?i) makes the pattern case-insensitive

    df1_minor = df1[df1[comment_col1].str.contains(minor_pattern, regex=True, na=False)]
    df2_minor = df2[df2[comment_col2].str.contains(minor_pattern, regex=True, na=False)]

    # Get titles for minor issues
    df1_minor_titles = set(df1_minor[title_col1])
    df2_minor_titles = set(df2_minor[title_col2])

    # Compare by titles for minor issues
    minor_in_file1_only_titles = df1_minor_titles - df2_minor_titles
    minor_in_file2_only_titles = df2_minor_titles - df1_minor_titles
    minor_in_both_titles = df1_minor_titles & df2_minor_titles

    # Create copies of the dataframes with only the columns we want
    df1_copy = df1[columns1].copy()
    df2_copy = df2[columns2].copy()

    # Create a custom status column for display with "Minor Bug" label
    df1_copy['Status Display'] = df1_copy[status_col1]
    df2_copy['Status Display'] = df2_copy[status_col2]

    # Mark minor bugs based on title match
    df1_copy.loc[df1_copy[title_col1].isin(df1_minor_titles), 'Status Display'] = 'Minor Bug'
    df2_copy.loc[df2_copy[title_col2].isin(df2_minor_titles), 'Status Display'] = 'Minor Bug'

    # Add the custom status column to the list of columns
    columns1.append('Status Display')
    columns2.append('Status Display')
    column_map1['Status Display'] = 'Status Display'
    column_map2['Status Display'] = 'Status Display'

    # Get the list of column names for display
    display_cols1 = columns1
    display_cols2 = columns2

    # Create display titles with the file names
    display_names = {}
    for key, template in DISPLAY_NAMES.items():
        display_names[key] = template.format(file1_name=display_file1_name, file2_name=display_file2_name)

    # Prepare result dataframes for tables
    result_tables = {
        'failed_file1_only': df1_copy[df1_copy[case_id_col1].isin(fail_in_file1_only_ids)][display_cols1],
        'failed_file2_only': df2_copy[df2_copy[case_id_col2].isin(fail_in_file2_only_ids)][display_cols2],
        'passed_file1_only': df1_copy[df1_copy[case_id_col1].isin(pass_in_file1_only_ids)][display_cols1],
        'passed_file2_only': df2_copy[df2_copy[case_id_col2].isin(pass_in_file2_only_ids)][display_cols2],
        'passed_both': df1_copy[df1_copy[case_id_col1].isin(pass_in_both_ids)][display_cols1],
    }

    # Process failed cases by plan
    failed_by_plan_tables = {}

    # Create separate dictionaries for failed cases by plan categories
    file1_failed_only_by_plan = {}
    file2_failed_only_by_plan = {}
    both_failed_by_plan = {}

    # Get failed cases only in file1, organized by plan
    if plan_col1:
        df1_failed_only = df1_copy[df1_copy[case_id_col1].isin(fail_in_file1_only_ids)]
        if not df1_failed_only.empty:
            for plan_name, group in df1_failed_only.groupby(plan_col1):
                plan_key = f"{display_file1_name} Only - {plan_name}"
                file1_failed_only_by_plan[plan_key] = group

    # Get failed cases only in file2, organized by plan
    if plan_col2:
        df2_failed_only = df2_copy[df2_copy[case_id_col2].isin(fail_in_file2_only_ids)]
        if not df2_failed_only.empty:
            for plan_name, group in df2_failed_only.groupby(plan_col2):
                plan_key = f"{display_file2_name} Only - {plan_name}"
                file2_failed_only_by_plan[plan_key] = group

    # Add all categorized plan tables to the failed_by_plan_tables
    failed_by_plan_tables.update(file1_failed_only_by_plan)
    failed_by_plan_tables.update(file2_failed_only_by_plan)
    failed_by_plan_tables.update(both_failed_by_plan)

    # Also keep the original complete plan lists for backward compatibility
    # Process failed cases by plan for file 1
    if plan_col1:
        df1_failed_copy = df1_copy[df1_copy[case_id_col1].isin(df1_fail_ids)]
        if not df1_failed_copy.empty:
            file1_failed_by_plan = {}
            for plan_name, group in df1_failed_copy.groupby(plan_col1):
                plan_key = f"{display_file1_name} - {plan_name}"
                file1_failed_by_plan[plan_key] = group
            failed_by_plan_tables.update(file1_failed_by_plan)

    # Process failed cases by plan for file 2
    if plan_col2:
        df2_failed_copy = df2_copy[df2_copy[case_id_col2].isin(df2_fail_ids)]
        if not df2_failed_copy.empty:
            file2_failed_by_plan = {}
            for plan_name, group in df2_failed_copy.groupby(plan_col2):
                plan_key = f"{display_file2_name} - {plan_name}"
                file2_failed_by_plan[plan_key] = group
            failed_by_plan_tables.update(file2_failed_by_plan)

    # Add the failed by plan tables to the result
    result_tables['failed_by_plan'] = failed_by_plan_tables

    # NEW: Compare failed cases by plan and title
    plan_title_comparison = compare_failed_cases_by_plan_and_title(
        df1, df2,
        case_id_col1, title_col1, plan_col1, status_col1,
        case_id_col2, title_col2, plan_col2, status_col2,
        display_file1_name, display_file2_name
    )

    # Process the plan title comparison results for display
    failed_by_plan_title_tables = {}
    for plan_key, plan_df in plan_title_comparison.items():
        if not plan_df.empty:
            # Only include columns that are in display_cols for each dataframe
            if plan_key.startswith(display_file1_name):
                display_cols = display_cols1
            else:
                display_cols = display_cols2

            # Make sure all necessary columns are included
            actual_cols = [col for col in display_cols if col in plan_df.columns]
            failed_by_plan_title_tables[plan_key] = plan_df[actual_cols]

    # Add the plan-title comparison to the result
    result_tables['failed_by_plan_title'] = failed_by_plan_title_tables

    # Get the dataframes for minor issues
    df1_minor_copy = df1_copy[df1_copy[title_col1].isin(df1_minor_titles)]
    df2_minor_copy = df2_copy[df2_copy[title_col2].isin(df2_minor_titles)]

    # All minor issues from both files
    result_tables['minor_all'] = pd.concat([
        df1_minor_copy.assign(Source=display_file1_name),
        df2_minor_copy.assign(Source=display_file2_name)
    ])

    # Process minor bugs by plan
    minor_by_plan_tables = {}

    # Create separate dictionaries for minor bugs by plan categories
    file1_only_by_plan = {}
    file2_only_by_plan = {}
    both_by_plan = {}

    # Get minor bugs only in file1, organized by plan
    if plan_col1:
        df1_minor_only = df1_minor_copy[df1_minor_copy[title_col1].isin(minor_in_file1_only_titles)]
        if not df1_minor_only.empty:
            for plan_name, group in df1_minor_only.groupby(plan_col1):
                plan_key = f"{display_file1_name} Only - {plan_name}"
                file1_only_by_plan[plan_key] = group

    # Get minor bugs only in file2, organized by plan
    if plan_col2:
        df2_minor_only = df2_minor_copy[df2_minor_copy[title_col2].isin(minor_in_file2_only_titles)]
        if not df2_minor_only.empty:
            for plan_name, group in df2_minor_only.groupby(plan_col2):
                plan_key = f"{display_file2_name} Only - {plan_name}"
                file2_only_by_plan[plan_key] = group

    # Get minor bugs in both files, organized by plan
    if minor_in_both_titles:
        df1_minor_both = df1_minor_copy[df1_minor_copy[title_col1].isin(minor_in_both_titles)]
        if plan_col1 and not df1_minor_both.empty:
            for plan_name, group in df1_minor_both.groupby(plan_col1):
                plan_key = f"Both Files - {plan_name}"
                both_by_plan[plan_key] = group

    # Add all categorized plan tables to the minor_by_plan_tables
    minor_by_plan_tables.update(file1_only_by_plan)
    minor_by_plan_tables.update(file2_only_by_plan)
    minor_by_plan_tables.update(both_by_plan)

    # Also keep the original complete plan lists for backward compatibility
    # Process minor bugs by plan for file 1
    if plan_col1 and not df1_minor_copy.empty:
        file1_minor_by_plan = {}
        for plan_name, group in df1_minor_copy.groupby(plan_col1):
            plan_key = f"{display_file1_name} - {plan_name}"
            file1_minor_by_plan[plan_key] = group
        minor_by_plan_tables.update(file1_minor_by_plan)

    # Process minor bugs by plan for file 2
    if plan_col2 and not df2_minor_copy.empty:
        file2_minor_by_plan = {}
        for plan_name, group in df2_minor_copy.groupby(plan_col2):
            plan_key = f"{display_file2_name} - {plan_name}"
            file2_minor_by_plan[plan_key] = group
        minor_by_plan_tables.update(file2_minor_by_plan)

    # Add the minor by plan tables to the result
    result_tables['minor_by_plan'] = minor_by_plan_tables

    result_tables['minor_file1_only'] = df1_minor_copy[df1_minor_copy[title_col1].isin(minor_in_file1_only_titles)][display_cols1]
    result_tables['minor_file2_only'] = df2_minor_copy[df2_minor_copy[title_col2].isin(minor_in_file2_only_titles)][display_cols2]

    # Cases with minor issues in both
    if minor_in_both_titles:
        # Find cases with minor issues in both files based on Title
        df1_minor_both = df1_minor_copy[df1_minor_copy[title_col1].isin(minor_in_both_titles)].copy()
        df2_minor_both = df2_minor_copy[df2_minor_copy[title_col2].isin(minor_in_both_titles)].copy()

        # Prepare columns for merging
        merge_cols = [title_col1] if title_col1 == title_col2 else []

        # If title columns have different names, rename one to match for merge
        if title_col1 != title_col2:
            df2_minor_both = df2_minor_both.rename(columns={title_col2: title_col1})
            merge_cols = [title_col1]

        # Add file identifier to the column names for clarity
        rename_cols1 = {}
        rename_cols2 = {}

        for col in df1_minor_both.columns:
            if col not in merge_cols and col != 'Status Display':
                rename_cols1[col] = f"{col} ({display_file1_name})"

        for col in df2_minor_both.columns:
            if col not in merge_cols and col != 'Status Display':
                rename_cols2[col] = f"{col} ({display_file2_name})"

        if rename_cols1:
            df1_minor_both = df1_minor_both.rename(columns=rename_cols1)
        if rename_cols2:
            df2_minor_both = df2_minor_both.rename(columns=rename_cols2)

        # Merge by title
        try:
            minor_both_merged = pd.merge(df1_minor_both, df2_minor_both, on=merge_cols, how="inner")

            # Rename the duplicate Status Display column
            if 'Status Display_x' in minor_both_merged.columns and 'Status Display_y' in minor_both_merged.columns:
                minor_both_merged = minor_both_merged.rename(columns={
                    'Status Display_x': f'Status ({display_file1_name})',
                    'Status Display_y': f'Status ({display_file2_name})'
                })

            result_tables['minor_both'] = minor_both_merged
        except Exception as e:
            # print(f"Error merging dataframes for minor issues: {str(e)}")
            # Use a simple dataframe instead
            result_tables['minor_both'] = df1_minor_both
    else:
        # Create empty dataframe if no minor issues in both
        result_tables['minor_both'] = pd.DataFrame(columns=[title_col1])

    # Convert all dataframes to HTML tables with bootstrap styling
    html_tables = {}
    for key, df in result_tables.items():
        # Special handling for minor_by_plan and failed_by_plan_title which are dictionaries of dataframes
        if key in ['minor_by_plan', 'failed_by_plan_title']:
            html_tables[key] = {}
            for plan_key, plan_df in df.items():
                if not plan_df.empty:
                    # Find comment column in the dataframe if it exists
                    comment_cols = [col for col in plan_df.columns if "comment" in str(col).lower() or "note" in str(col).lower() or "description" in str(col).lower()]

                    # Make a copy of the dataframe to avoid modifying the original
                    plan_df_display = plan_df.copy()

                    # Generate a unique ID for each row for later reference
                    plan_df_display['_row_id'] = [f"row_{key}_{plan_key}_{i}" for i in range(len(plan_df_display))]

                    # Truncate long texts for better display with expandable tooltips
                    for col in plan_df_display.columns:
                        if col == '_row_id':
                            continue

                        # Check if this column's content is string type (object dtype) before processing
                        if pd.api.types.is_object_dtype(plan_df_display[col]):
                            # Add special handling for comment columns
                            if comment_cols and col in comment_cols:
                                # For comment columns, create clickable elements with the full text stored in a data attribute
                                plan_df_display[col] = plan_df_display.apply(
                                    lambda row: create_comment_html(row[col], row['_row_id']) if isinstance(row[col], str) and len(str(row[col])) > 150 else str(row[col]),
                                    axis=1
                                )
                            else:
                                # For other text columns, just truncate with tooltip
                                plan_df_display[col] = plan_df_display[col].apply(
                                    lambda x: f'<span title="{html.escape(str(x))}">{html.escape(str(x)[:150])}{("..." if len(str(x)) > 150 else "")}</span>'
                                    if isinstance(x, str) and len(str(x)) > 150 else str(x)
                                )

                    # Remove the temporary row ID column before rendering
                    plan_df_display = plan_df_display.drop(columns=['_row_id'])

                    html_tables[key][plan_key] = plan_df_display.to_html(
                        classes='table table-striped table-bordered table-hover table-sm',
                        index=False,
                        escape=False,
                        table_id=f'table-{key}-{plan_key.replace(" ", "-").lower()}'
                    )

                    # Add hidden divs with full comment text
                    comments_data = {}
                    for i, row in plan_df.iterrows():
                        row_id = f"row_{key}_{plan_key}_{i}"
                        for col in comment_cols:
                            if col in row and pd.notna(row[col]) and isinstance(row[col], str) and len(str(row[col])) > 150:
                                comments_data[f"{row_id}_{col}"] = str(row[col])

                    if comments_data:
                        html_tables[key][plan_key] += f'<script>var commentsData = commentsData || {{}}; Object.assign(commentsData, {json.dumps(comments_data)});</script>'
        elif key != 'failed_by_plan' and not isinstance(df, dict):
            if not df.empty:
                # Find comment column in the dataframe if it exists
                comment_cols = [col for col in df.columns if "comment" in str(col).lower() or "note" in str(col).lower() or "description" in str(col).lower()]

                # Make a copy of the dataframe to avoid modifying the original
                df_display = df.copy()

                # Generate a unique ID for each row for later reference
                df_display['_row_id'] = [f"row_{key}_{i}" for i in range(len(df_display))]

                # Truncate long texts for better display with expandable tooltips
                for col in df_display.columns:
                    if col == '_row_id':
                        continue

                    # FIX: Check if this column's content is string type (object dtype) before processing
                    if pd.api.types.is_object_dtype(df_display[col]):
                        # Add special handling for comment columns
                        if comment_cols and col in comment_cols:
                            # For comment columns, create clickable elements with the full text stored in a data attribute
                            df_display[col] = df_display.apply(
                                lambda row: create_comment_html(row[col], row['_row_id']) if isinstance(row[col], str) and len(str(row[col])) > 150 else str(row[col]),
                                axis=1
                            )
                        else:
                            # For other text columns, just truncate with tooltip
                            df_display[col] = df_display[col].apply(
                                lambda x: f'<span title="{html.escape(str(x))}">{html.escape(str(x)[:150])}{("..." if len(str(x)) > 150 else "")}</span>'
                                if isinstance(x, str) and len(str(x)) > 150 else str(x)
                            )

                # Remove the temporary row ID column before rendering
                df_display = df_display.drop(columns=['_row_id'])

                html_tables[key] = df_display.to_html(
                    classes='table table-striped table-bordered table-hover table-sm',
                    index=False,
                    escape=False,
                    table_id=f'table-{key}'
                )

                # Add hidden divs with full comment text
                comments_data = {}
                for i, row in df.iterrows():
                    row_id = f"row_{key}_{i}"
                    for col in comment_cols:
                        if col in row and pd.notna(row[col]) and isinstance(row[col], str) and len(str(row[col])) > 150:
                            comments_data[f"{row_id}_{col}"] = str(row[col])

                if comments_data:
                    html_tables[key] += f'<script>var commentsData = commentsData || {{}}; Object.assign(commentsData, {json.dumps(comments_data)});</script>'

            else:
                html_tables[key] = "<p class='text-muted'>No data available</p>"

    # Add file names and display titles to the result
    html_tables['file1_name'] = display_file1_name
    html_tables['file2_name'] = display_file2_name
    html_tables['display_names'] = display_names

    return html_tables

def find_tested_by_column(df):
    """Find the Tested By column in dataframe"""
    possible_names = ["tested by", "testedby", "tested", "tester", "executor"]

    for col in df.columns:
        if col.lower() in possible_names or "tested" in col.lower() and "by" in col.lower():
            return col

    return None

def compare_failed_cases_by_plan_and_title(df1, df2, case_id_col1, title_col1, plan_col1, status_col1,
                                          case_id_col2, title_col2, plan_col2, status_col2,
                                          display_file1_name, display_file2_name):
    """
    Compare failed cases between two files, identifying cases that exist in one plan but not in another,
    based on title comparison instead of case ID.
    """
    # Get the failed cases from each file
    df1_failed = df1[df1[status_col1].str.lower() == "failed"].copy()
    df2_failed = df2[df2[status_col2].str.lower() == "failed"].copy()

    # If either dataframe is empty or missing essential columns, return empty dict
    if (df1_failed.empty or df2_failed.empty or
        not plan_col1 or not plan_col2 or
        not title_col1 or not title_col2):
        return {}

    # Get all unique plan names from both files
    plans1 = df1_failed[plan_col1].unique()
    plans2 = df2_failed[plan_col2].unique()

    # Initialize result dictionary
    plan_comparison_results = {}

    # For each plan in file1, find cases not in any plan in file2 based on title
    for plan1 in plans1:
        if pd.isna(plan1) or plan1 == "":
            continue

        plan1_cases = df1_failed[df1_failed[plan_col1] == plan1]
        plan1_titles = set(plan1_cases[title_col1])

        # Find all titles in file2 failed cases
        all_file2_titles = set(df2_failed[title_col2])

        # Cases in plan1 with titles not in any plan in file2
        exclusive_cases = plan1_cases[~plan1_cases[title_col1].isin(all_file2_titles)]

        if not exclusive_cases.empty:
            key = f"{display_file1_name} Plan '{plan1}' Exclusive Failures"
            plan_comparison_results[key] = exclusive_cases

    # For each plan in file2, find cases not in any plan in file1 based on title
    for plan2 in plans2:
        if pd.isna(plan2) or plan2 == "":
            continue

        plan2_cases = df2_failed[df2_failed[plan_col2] == plan2]
        plan2_titles = set(plan2_cases[title_col2])

        # Find all titles in file1 failed cases
        all_file1_titles = set(df1_failed[title_col1])

        # Cases in plan2 with titles not in any plan in file1
        exclusive_cases = plan2_cases[~plan2_cases[title_col2].isin(all_file1_titles)]

        if not exclusive_cases.empty:
            key = f"{display_file2_name} Plan '{plan2}' Exclusive Failures"
            plan_comparison_results[key] = exclusive_cases

    return plan_comparison_results

def create_comment_html(text, row_id):
    """Compare test results and return dataframes for display in tables"""
    # Create short names for files (up to 10 chars)
    file1_name = os.path.basename(file1_path).split('.')[0]
    file2_name = os.path.basename(file2_path).split('.')[0]

    # Use custom labels if provided
    if custom_label1 and custom_label1.strip():
        display_file1_name = custom_label1.strip()
    else:
        # Create shortened names for display
        display_file1_name = file1_name[:15] if len(file1_name) > 15 else file1_name

    if custom_label2 and custom_label2.strip():
        display_file2_name = custom_label2.strip()
    else:
        display_file2_name = file2_name[:15] if len(file2_name) > 15 else file2_name

    # Load data from files - print column names for debugging
    # print(f"Reading file 1: {file1_path}")
    df1 = pd.read_csv(file1_path, encoding='utf-8', on_bad_lines='skip')
    # print(f"File 1 columns: {df1.columns.tolist()}")

   #  print(f"Reading file 2: {file2_path}")
    df2 = pd.read_csv(file2_path, encoding='utf-8', on_bad_lines='skip')
    # print(f"File 2 columns: {df2.columns.tolist()}")

    # Find important columns in dataframes with case-insensitive matching
    case_id_col1 = find_case_id_column(df1)
    status_col1 = find_status_column(df1)
    title_col1 = find_title_column(df1)
    comment_col1 = find_comment_column(df1)
    tested_by_col1 = find_tested_by_column(df1)
    plan_col1 = find_plan_column(df1)

    case_id_col2 = find_case_id_column(df2)
    status_col2 = find_status_column(df2)
    title_col2 = find_title_column(df2)
    comment_col2 = find_comment_column(df2)
    tested_by_col2 = find_tested_by_column(df2)
    plan_col2 = find_plan_column(df2)

    # Verify required columns exist
    if not case_id_col1 or not status_col1:
        raise ValueError(f"Could not find 'Case ID' and 'Status' columns in first file. Available columns: {df1.columns.tolist()}")
    if not case_id_col2 or not status_col2:
        raise ValueError(f"Could not find 'Case ID' and 'Status' columns in second file. Available columns: {df2.columns.tolist()}")
    if not title_col1:
        raise ValueError(f"Could not find 'Title' column in first file. Available columns: {df1.columns.tolist()}")
    if not title_col2:
        raise ValueError(f"Could not find 'Title' column in second file. Available columns: {df2.columns.tolist()}")

    # Define columns we care about - only include those that exist
    columns1 = [case_id_col1]
    columns2 = [case_id_col2]

    # Keep original column names
    column_map1 = {col: col for col in df1.columns}
    column_map2 = {col: col for col in df2.columns}

    # Add important columns first
    if title_col1:
        columns1.append(title_col1)
    if title_col2:
        columns2.append(title_col2)

    if comment_col1:
        columns1.append(comment_col1)
    else:
        df1["Comment"] = ""
        comment_col1 = "Comment"
        columns1.append(comment_col1)
        column_map1[comment_col1] = "Comment"

    if comment_col2:
        columns2.append(comment_col2)
    else:
        df2["Comment"] = ""
        comment_col2 = "Comment"
        columns2.append(comment_col2)
        column_map2[comment_col2] = "Comment"

    # Add Plan column if it exists
    if plan_col1:
        columns1.append(plan_col1)
    if plan_col2:
        columns2.append(plan_col2)

    # Add Status column
    columns1.append(status_col1)
    columns2.append(status_col2)

    # Add Tested By if available
    if tested_by_col1:
        columns1.append(tested_by_col1)
    if tested_by_col2:
        columns2.append(tested_by_col2)

    # Handle NaN values in the Comment column
    if comment_col1:
        df1[comment_col1] = df1[comment_col1].fillna("")
    if comment_col2:
        df2[comment_col2] = df2[comment_col2].fillna("")

    # Handle NaN values in the Plan column if it exists
    if plan_col1:
        df1[plan_col1] = df1[plan_col1].fillna("No Plan")
    if plan_col2:
        df2[plan_col2] = df2[plan_col2].fillna("No Plan")

    # Get passed and failed tests
    df1_passed = df1[df1[status_col1].str.lower() == "passed"]
    df1_failed = df1[df1[status_col1].str.lower() == "failed"]
    df2_passed = df2[df2[status_col2].str.lower() == "passed"]
    df2_failed = df2[df2[status_col2].str.lower() == "failed"]

    # Create sets of Case IDs
    df1_fail_ids = set(df1_failed[case_id_col1])
    df2_fail_ids = set(df2_failed[case_id_col2])
    df1_pass_ids = set(df1_passed[case_id_col1])
    df2_pass_ids = set(df2_passed[case_id_col2])

    # Compare failed cases
    fail_in_file1_only_ids = df1_fail_ids - df2_fail_ids
    fail_in_file2_only_ids = df2_fail_ids - df1_fail_ids
    fail_in_both_ids = df1_fail_ids & df2_fail_ids

    # Compare passed cases
    pass_in_file1_only_ids = df1_pass_ids - df2_pass_ids
    pass_in_file2_only_ids = df2_pass_ids - df1_pass_ids
    pass_in_both_ids = df1_pass_ids & df2_pass_ids

    # Find minor issues - looking for any variation of 'minor' in comments
    # Use a more flexible pattern to match variations like 'minor', 'Minor', 'MINOR', etc.
    minor_pattern = r"(?i)\bminor\b"  # (?i) makes the pattern case-insensitive

    df1_minor = df1[df1[comment_col1].str.contains(minor_pattern, regex=True, na=False)]
    df2_minor = df2[df2[comment_col2].str.contains(minor_pattern, regex=True, na=False)]

    # Get titles for minor issues
    df1_minor_titles = set(df1_minor[title_col1])
    df2_minor_titles = set(df2_minor[title_col2])

    # Compare by titles for minor issues
    minor_in_file1_only_titles = df1_minor_titles - df2_minor_titles
    minor_in_file2_only_titles = df2_minor_titles - df1_minor_titles
    minor_in_both_titles = df1_minor_titles & df2_minor_titles

    # Create copies of the dataframes with only the columns we want
    df1_copy = df1[columns1].copy()
    df2_copy = df2[columns2].copy()

    # Create a custom status column for display with "Minor Bug" label
    df1_copy['Status Display'] = df1_copy[status_col1]
    df2_copy['Status Display'] = df2_copy[status_col2]

    # Mark minor bugs based on title match
    df1_copy.loc[df1_copy[title_col1].isin(df1_minor_titles), 'Status Display'] = 'Minor Bug'
    df2_copy.loc[df2_copy[title_col2].isin(df2_minor_titles), 'Status Display'] = 'Minor Bug'

    # Add the custom status column to the list of columns
    columns1.append('Status Display')
    columns2.append('Status Display')
    column_map1['Status Display'] = 'Status Display'
    column_map2['Status Display'] = 'Status Display'

    # Get the list of column names for display
    display_cols1 = columns1
    display_cols2 = columns2

    # Create display titles with the file names
    display_names = {}
    for key, template in DISPLAY_NAMES.items():
        display_names[key] = template.format(file1_name=display_file1_name, file2_name=display_file2_name)
    # Prepare result dataframes for tables
    result_tables = {
        'failed_file1_only': df1_copy[df1_copy[case_id_col1].isin(fail_in_file1_only_ids)][display_cols1],
        'failed_file2_only': df2_copy[df2_copy[case_id_col2].isin(fail_in_file2_only_ids)][display_cols2],
        'passed_file1_only': df1_copy[df1_copy[case_id_col1].isin(pass_in_file1_only_ids)][display_cols1],
        'passed_file2_only': df2_copy[df2_copy[case_id_col2].isin(pass_in_file2_only_ids)][display_cols2],
        'passed_both': df1_copy[df1_copy[case_id_col1].isin(pass_in_both_ids)][display_cols1],
    }

    # Process failed cases by plan
    failed_by_plan_tables = {}

    # Create separate dictionaries for failed cases by plan categories
    file1_failed_only_by_plan = {}
    file2_failed_only_by_plan = {}
    both_failed_by_plan = {}

    # Get failed cases only in file1, organized by plan
    if plan_col1:
        df1_failed_only = df1_copy[df1_copy[case_id_col1].isin(fail_in_file1_only_ids)]
        if not df1_failed_only.empty:
            for plan_name, group in df1_failed_only.groupby(plan_col1):
                plan_key = f"{display_file1_name} Only - {plan_name}"
                file1_failed_only_by_plan[plan_key] = group

    # Get failed cases only in file2, organized by plan
    if plan_col2:
        df2_failed_only = df2_copy[df2_copy[case_id_col2].isin(fail_in_file2_only_ids)]
        if not df2_failed_only.empty:
            for plan_name, group in df2_failed_only.groupby(plan_col2):
                plan_key = f"{display_file2_name} Only - {plan_name}"
                file2_failed_only_by_plan[plan_key] = group

    # Add all categorized plan tables to the failed_by_plan_tables
    failed_by_plan_tables.update(file1_failed_only_by_plan)
    failed_by_plan_tables.update(file2_failed_only_by_plan)
    failed_by_plan_tables.update(both_failed_by_plan)

    # Also keep the original complete plan lists for backward compatibility
    # Process failed cases by plan for file 1
    if plan_col1:
        df1_failed_copy = df1_copy[df1_copy[case_id_col1].isin(df1_fail_ids)]
        if not df1_failed_copy.empty:
            file1_failed_by_plan = {}
            for plan_name, group in df1_failed_copy.groupby(plan_col1):
                plan_key = f"{display_file1_name} - {plan_name}"
                file1_failed_by_plan[plan_key] = group
            failed_by_plan_tables.update(file1_failed_by_plan)

    # Process failed cases by plan for file 2
    if plan_col2:
        df2_failed_copy = df2_copy[df2_copy[case_id_col2].isin(df2_fail_ids)]
        if not df2_failed_copy.empty:
            file2_failed_by_plan = {}
            for plan_name, group in df2_failed_copy.groupby(plan_col2):
                plan_key = f"{display_file2_name} - {plan_name}"
                file2_failed_by_plan[plan_key] = group
            failed_by_plan_tables.update(file2_failed_by_plan)

    # Add the failed by plan tables to the result
    result_tables['failed_by_plan'] = failed_by_plan_tables

    # Get the dataframes for minor issues
    df1_minor_copy = df1_copy[df1_copy[title_col1].isin(df1_minor_titles)]
    df2_minor_copy = df2_copy[df2_copy[title_col2].isin(df2_minor_titles)]

    # All minor issues from both files
    result_tables['minor_all'] = pd.concat([
        df1_minor_copy.assign(Source=display_file1_name),
        df2_minor_copy.assign(Source=display_file2_name)
    ])

    # Process minor bugs by plan
    minor_by_plan_tables = {}

    # Create separate dictionaries for minor bugs by plan categories
    file1_only_by_plan = {}
    file2_only_by_plan = {}
    both_by_plan = {}

    # Get minor bugs only in file1, organized by plan
    if plan_col1:
        df1_minor_only = df1_minor_copy[df1_minor_copy[title_col1].isin(minor_in_file1_only_titles)]
        if not df1_minor_only.empty:
            for plan_name, group in df1_minor_only.groupby(plan_col1):
                plan_key = f"{display_file1_name} Only - {plan_name}"
                file1_only_by_plan[plan_key] = group

    # Get minor bugs only in file2, organized by plan
    if plan_col2:
        df2_minor_only = df2_minor_copy[df2_minor_copy[title_col2].isin(minor_in_file2_only_titles)]
        if not df2_minor_only.empty:
            for plan_name, group in df2_minor_only.groupby(plan_col2):
                plan_key = f"{display_file2_name} Only - {plan_name}"
                file2_only_by_plan[plan_key] = group

    # Get minor bugs in both files, organized by plan
    if minor_in_both_titles:
        df1_minor_both = df1_minor_copy[df1_minor_copy[title_col1].isin(minor_in_both_titles)]
        if plan_col1 and not df1_minor_both.empty:
            for plan_name, group in df1_minor_both.groupby(plan_col1):
                plan_key = f"Both Files - {plan_name}"
                both_by_plan[plan_key] = group

    # Add all categorized plan tables to the minor_by_plan_tables
    minor_by_plan_tables.update(file1_only_by_plan)
    minor_by_plan_tables.update(file2_only_by_plan)
    minor_by_plan_tables.update(both_by_plan)

    # Also keep the original complete plan lists for backward compatibility
    # Process minor bugs by plan for file 1
    if plan_col1 and not df1_minor_copy.empty:
        file1_minor_by_plan = {}
        for plan_name, group in df1_minor_copy.groupby(plan_col1):
            plan_key = f"{display_file1_name} - {plan_name}"
            file1_minor_by_plan[plan_key] = group
        minor_by_plan_tables.update(file1_minor_by_plan)

    # Process minor bugs by plan for file 2
    if plan_col2 and not df2_minor_copy.empty:
        file2_minor_by_plan = {}
        for plan_name, group in df2_minor_copy.groupby(plan_col2):
            plan_key = f"{display_file2_name} - {plan_name}"
            file2_minor_by_plan[plan_key] = group
        minor_by_plan_tables.update(file2_minor_by_plan)

    # Add the minor by plan tables to the result
    result_tables['minor_by_plan'] = minor_by_plan_tables

    result_tables['minor_file1_only'] = df1_minor_copy[df1_minor_copy[title_col1].isin(minor_in_file1_only_titles)][display_cols1]
    result_tables['minor_file2_only'] = df2_minor_copy[df2_minor_copy[title_col2].isin(minor_in_file2_only_titles)][display_cols2]

    # Cases with minor issues in both
    if minor_in_both_titles:
        # Find cases with minor issues in both files based on Title
        df1_minor_both = df1_minor_copy[df1_minor_copy[title_col1].isin(minor_in_both_titles)].copy()
        df2_minor_both = df2_minor_copy[df2_minor_copy[title_col2].isin(minor_in_both_titles)].copy()

        # Prepare columns for merging
        merge_cols = [title_col1] if title_col1 == title_col2 else []

        # If title columns have different names, rename one to match for merge
        if title_col1 != title_col2:
            df2_minor_both = df2_minor_both.rename(columns={title_col2: title_col1})
            merge_cols = [title_col1]

        # Add file identifier to the column names for clarity
        rename_cols1 = {}
        rename_cols2 = {}

        for col in df1_minor_both.columns:
            if col not in merge_cols and col != 'Status Display':
                rename_cols1[col] = f"{col} ({display_file1_name})"

        for col in df2_minor_both.columns:
            if col not in merge_cols and col != 'Status Display':
                rename_cols2[col] = f"{col} ({display_file2_name})"

        if rename_cols1:
            df1_minor_both = df1_minor_both.rename(columns=rename_cols1)
        if rename_cols2:
            df2_minor_both = df2_minor_both.rename(columns=rename_cols2)

        # Merge by title
        try:
            minor_both_merged = pd.merge(df1_minor_both, df2_minor_both, on=merge_cols, how="inner")

            # Rename the duplicate Status Display column
            if 'Status Display_x' in minor_both_merged.columns and 'Status Display_y' in minor_both_merged.columns:
                minor_both_merged = minor_both_merged.rename(columns={
                    'Status Display_x': f'Status ({display_file1_name})',
                    'Status Display_y': f'Status ({display_file2_name})'
                })

            result_tables['minor_both'] = minor_both_merged
        except Exception as e:
          #   print(f"Error merging dataframes for minor issues: {str(e)}")
            # Use a simple dataframe instead
            result_tables['minor_both'] = df1_minor_both
    else:
        # Create empty dataframe if no minor issues in both
        result_tables['minor_both'] = pd.DataFrame(columns=[title_col1])

    # Convert all dataframes to HTML tables with bootstrap styling
    html_tables = {}
    for key, df in result_tables.items():
        # Special handling for minor_by_plan which is a dictionary of dataframes
        if key == 'minor_by_plan':
            html_tables[key] = {}
            for plan_key, plan_df in df.items():
                if not plan_df.empty:
                    # Find comment column in the dataframe if it exists
                    comment_cols = [col for col in plan_df.columns if "comment" in str(col).lower() or "note" in str(col).lower() or "description" in str(col).lower()]

                    # Make a copy of the dataframe to avoid modifying the original
                    plan_df_display = plan_df.copy()

                    # Generate a unique ID for each row for later reference
                    plan_df_display['_row_id'] = [f"row_{key}_{plan_key}_{i}" for i in range(len(plan_df_display))]

                    # Truncate long texts for better display with expandable tooltips
                    for col in plan_df_display.columns:
                        if col == '_row_id':
                            continue

                        # Check if this column's content is string type (object dtype) before processing
                        if pd.api.types.is_object_dtype(plan_df_display[col]):
                            # Add special handling for comment columns
                            if comment_cols and col in comment_cols:
                                # For comment columns, create clickable elements with the full text stored in a data attribute
                                plan_df_display[col] = plan_df_display.apply(
                                    lambda row: create_comment_html(row[col], row['_row_id']) if isinstance(row[col], str) and len(str(row[col])) > 150 else str(row[col]),
                                    axis=1
                                )
                            else:
                                # For other text columns, just truncate with tooltip
                                plan_df_display[col] = plan_df_display[col].apply(
                                    lambda x: f'<span title="{html.escape(str(x))}">{html.escape(str(x)[:150])}{("..." if len(str(x)) > 150 else "")}</span>'
                                    if isinstance(x, str) and len(str(x)) > 150 else str(x)
                                )

                    # Remove the temporary row ID column before rendering
                    plan_df_display = plan_df_display.drop(columns=['_row_id'])

                    html_tables[key][plan_key] = plan_df_display.to_html(
                        classes='table table-striped table-bordered table-hover table-sm',
                        index=False,
                        escape=False,
                        table_id=f'table-{key}-{plan_key.replace(" ", "-").lower()}'
                    )

                    # Add hidden divs with full comment text
                    comments_data = {}
                    for i, row in plan_df.iterrows():
                        row_id = f"row_{key}_{plan_key}_{i}"
                        for col in comment_cols:
                            if col in row and pd.notna(row[col]) and isinstance(row[col], str) and len(str(row[col])) > 150:
                                comments_data[f"{row_id}_{col}"] = str(row[col])

                    if comments_data:
                        html_tables[key][plan_key] += f'<script>var commentsData = commentsData || {{}}; Object.assign(commentsData, {json.dumps(comments_data)});</script>'
        elif key != 'minor_by_plan' and not isinstance(df, dict):
            if not df.empty:
                # Find comment column in the dataframe if it exists
                comment_cols = [col for col in df.columns if "comment" in str(col).lower() or "note" in str(col).lower() or "description" in str(col).lower()]

                # Make a copy of the dataframe to avoid modifying the original
                df_display = df.copy()

                # Generate a unique ID for each row for later reference
                df_display['_row_id'] = [f"row_{key}_{i}" for i in range(len(df_display))]

                # Truncate long texts for better display with expandable tooltips
                for col in df_display.columns:
                    if col == '_row_id':
                        continue

                    # FIX: Check if this column's content is string type (object dtype) before processing
                    if pd.api.types.is_object_dtype(df_display[col]):
                        # Add special handling for comment columns
                        if comment_cols and col in comment_cols:
                            # For comment columns, create clickable elements with the full text stored in a data attribute
                            df_display[col] = df_display.apply(
                                lambda row: create_comment_html(row[col], row['_row_id']) if isinstance(row[col], str) and len(str(row[col])) > 150 else str(row[col]),
                                axis=1
                            )
                        else:
                            # For other text columns, just truncate with tooltip
                            df_display[col] = df_display[col].apply(
                                lambda x: f'<span title="{html.escape(str(x))}">{html.escape(str(x)[:150])}{("..." if len(str(x)) > 150 else "")}</span>'
                                if isinstance(x, str) and len(str(x)) > 150 else str(x)
                            )

                # Remove the temporary row ID column before rendering
                df_display = df_display.drop(columns=['_row_id'])

                html_tables[key] = df_display.to_html(
                    classes='table table-striped table-bordered table-hover table-sm',
                    index=False,
                    escape=False,
                    table_id=f'table-{key}'
                )

                # Add hidden divs with full comment text
                comments_data = {}
                for i, row in df.iterrows():
                    row_id = f"row_{key}_{i}"
                    for col in comment_cols:
                        if col in row and pd.notna(row[col]) and isinstance(row[col], str) and len(str(row[col])) > 150:
                            comments_data[f"{row_id}_{col}"] = str(row[col])

                if comments_data:
                    html_tables[key] += f'<script>var commentsData = commentsData || {{}}; Object.assign(commentsData, {json.dumps(comments_data)});</script>'

            else:
                html_tables[key] = "<p class='text-muted'>No data available</p>"

    # Add file names and display titles to the result
    html_tables['file1_name'] = display_file1_name
    html_tables['file2_name'] = display_file2_name
    html_tables['display_names'] = display_names

    return html_tables

def get_comparison_stats(file1_path, file2_path, custom_label1=None, custom_label2=None):
    """Generate statistics for the comparison"""
    # Create short names for files (up to 10 chars)
    file1_name = os.path.basename(file1_path).split('.')[0]
    file2_name = os.path.basename(file2_path).split('.')[0]

    # Use custom labels if provided
    if custom_label1 and custom_label1.strip():
        display_file1_name = custom_label1.strip()
    else:
        # Create shortened names for display
        display_file1_name = file1_name[:15] if len(file1_name) > 15 else file1_name

    if custom_label2 and custom_label2.strip():
        display_file2_name = custom_label2.strip()
    else:
        display_file2_name = file2_name[:15] if len(file2_name) > 15 else file2_name

    # Load data from files - print column names for debugging
    # print(f"Reading file 1: {file1_path}")
    df1 = pd.read_csv(file1_path, encoding='utf-8', on_bad_lines='skip')
    # print(f"File 1 columns: {df1.columns.tolist()}")

   #  print(f"Reading file 2: {file2_path}")
    df2 = pd.read_csv(file2_path, encoding='utf-8', on_bad_lines='skip')
   #  print(f"File 2 columns: {df2.columns.tolist()}")

    # Find the actual column names in df1 and df2
    case_id_col1 = find_case_id_column(df1)
    status_col1 = find_status_column(df1)
    title_col1 = find_title_column(df1)
    case_id_col2 = find_case_id_column(df2)
    status_col2 = find_status_column(df2)
    title_col2 = find_title_column(df2)

    if not case_id_col1 or not status_col1:
        raise ValueError(f"Could not find 'Case ID' and 'Status' columns in first file. Available columns: {df1.columns.tolist()}")
    if not case_id_col2 or not status_col2:
        raise ValueError(f"Could not find 'Case ID' and 'Status' columns in second file. Available columns: {df2.columns.tolist()}")
    if not title_col1:
        raise ValueError(f"Could not find 'Title' column in first file. Available columns: {df1.columns.tolist()}")
    if not title_col2:
        raise ValueError(f"Could not find 'Title' column in second file. Available columns: {df2.columns.tolist()}")

    # Find comment column in each dataframe
    comment_col1 = find_comment_column(df1)
    comment_col2 = find_comment_column(df2)

    # Find plan column in each dataframe
    plan_col1 = find_plan_column(df1)
    plan_col2 = find_plan_column(df2)

    # Handle NaN values in the Comment column
    if comment_col1:
        df1[comment_col1] = df1[comment_col1].fillna("")
    else:
        df1["Comment"] = ""
        comment_col1 = "Comment"

    if comment_col2:
        df2[comment_col2] = df2[comment_col2].fillna("")
    else:
        df2["Comment"] = ""
        comment_col2 = "Comment"

    # Get pass/fail counts
    df1_passed = df1[df1[status_col1].str.lower() == "passed"]
    df1_failed = df1[df1[status_col1].str.lower() == "failed"]
    df2_passed = df2[df2[status_col2].str.lower() == "passed"]
    df2_failed = df2[df2[status_col2].str.lower() == "failed"]

    # Create sets of Case IDs
    df1_pass_ids = set(df1_passed[case_id_col1])
    df1_fail_ids = set(df1_failed[case_id_col1])
    df2_pass_ids = set(df2_passed[case_id_col2])
    df2_fail_ids = set(df2_failed[case_id_col2])

    # Get minor issues - looking for any variation of 'minor' in comments
    # Use a more flexible pattern to match variations like 'minor', 'Minor', 'MINOR', etc.
    minor_pattern = r"(?i)\bminor\b"  # (?i) makes the pattern case-insensitive

    df1_minor = df1[df1[comment_col1].str.contains(minor_pattern, regex=True, na=False)]
    df2_minor = df2[df2[comment_col2].str.contains(minor_pattern, regex=True, na=False)]

    # Find titles of minor bug cases
    df1_minor_titles = set(df1_minor[title_col1])
    df2_minor_titles = set(df2_minor[title_col2])

    minor_in_file1_only_titles = df1_minor_titles - df2_minor_titles
    minor_in_file2_only_titles = df2_minor_titles - df1_minor_titles
    minor_in_both_titles = df1_minor_titles & df2_minor_titles

    # Compute statistics
    stats = {
        'file1_name': display_file1_name,
        'file2_name': display_file2_name,
        'file1_total': len(df1),
        'file2_total': len(df2),
        'file1_passed': len(df1_passed),
        'file1_failed': len(df1_failed),
        'file2_passed': len(df2_passed),
        'file2_failed': len(df2_failed),
        'file1_minor': len(df1_minor),
        'file2_minor': len(df2_minor),
        'fail_in_file1_only': len(df1_fail_ids - df2_fail_ids),
        'fail_in_file2_only': len(df2_fail_ids - df1_fail_ids),
        'fail_in_both': len(df1_fail_ids & df2_fail_ids),
        'pass_in_file1_only': len(df1_pass_ids - df2_pass_ids),
        'pass_in_file2_only': len(df2_pass_ids - df1_pass_ids),
        'pass_in_both': len(df1_pass_ids & df2_pass_ids),
        'minor_in_file1_only': len(minor_in_file1_only_titles),
        'minor_in_file2_only': len(minor_in_file2_only_titles),
        'minor_in_both': len(minor_in_both_titles)
    }

    return stats

@app.template_filter('count_table_rows')
def count_table_rows(html_table):
    """Count the number of rows in an HTML table, excluding header row"""
    if not html_table or not isinstance(html_table, str):
        return 0

    import re
    # Count <tr> tags but subtract 1 for the header row (if any)
    tr_count = len(re.findall(r'<tr>', html_table))
    return max(0, tr_count - 1) if tr_count > 0 else 0

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    if 'file1' not in request.files or 'file2' not in request.files:
        flash('Both files are required')
        return redirect(request.url)

    file1 = request.files['file1']
    file2 = request.files['file2']

    if file1.filename == '' or file2.filename == '':
        flash('Please select both files')
        return redirect(request.url)

    # Get custom labels from form (if any)
    custom_label1 = request.form.get('custom_label1', '').strip()
    custom_label2 = request.form.get('custom_label2', '').strip()

    if file1 and allowed_file(file1.filename) and file2 and allowed_file(file2.filename):
        # Save the files
        filename1 = secure_filename(file1.filename)
        filename2 = secure_filename(file2.filename)

        file1_path = os.path.join(app.config['UPLOAD_FOLDER'], filename1)
        file2_path = os.path.join(app.config['UPLOAD_FOLDER'], filename2)

        file1.save(file1_path)
        file2.save(file2_path)

        try:
            # Get comparison results directly with custom labels
            comparison_results = compare_test_results_as_tables(file1_path, file2_path, custom_label1, custom_label2)

            # Get the statistics from the processed data
            stats = get_comparison_stats(file1_path, file2_path, custom_label1, custom_label2)

            # Render results page with tables
            return render_template('results_table.html', stats=stats, results=comparison_results)
        except Exception as e:
            flash(f'Error processing files: {str(e)}')
            import traceback
            app.logger.error(f"Exception details: {traceback.format_exc()}")
            return redirect(url_for('index'))

    flash('Only CSV files are allowed')
    return redirect(url_for('index'))

def find_case_id_column(df):
    """Find the Case ID column in dataframe"""
    possible_names = ["case id", "caseid", "case_id", "id", "case", "testcase id"]

    for col in df.columns:
        if col.lower() in possible_names or "case" in col.lower() and "id" in col.lower():
            return col

    return None

def find_status_column(df):
    """Find the Status column in dataframe"""
    possible_names = ["status", "state", "test status", "teststatus", "result"]

    for col in df.columns:
        if col.lower() in possible_names:
            return col

    return None

def find_comment_column(df):
    """Find the Comment column in dataframe"""
    possible_names = ["comment", "comments", "note", "notes", "description"]

    for col in df.columns:
        if col.lower() in possible_names:
            return col

    return None

def find_title_column(df):
    """Find the Title column in dataframe"""
    possible_names = ["title", "name", "test title", "test name", "testname", "testtitle", "case title", "casetitle"]

    for col in df.columns:
        if col.lower() in possible_names:
            return col

    return None

def find_plan_column(df):
    """Find the Plan column in dataframe"""
    possible_names = ["plan", "test plan", "testplan"]

    for col in df.columns:
        if col.lower() in possible_names:
            return col

    return None

def find_tested_by_column(df):
    """Find the Tested By column in dataframe"""
    possible_names = ["tested by", "testedby", "tested", "tester", "executor"]

    for col in df.columns:
        if col.lower() in possible_names or "tested" in col.lower() and "by" in col.lower():
            return col

    return None

def create_comment_html(text, row_id):
    """Create HTML for a comment field with a clickable element for long text"""
    if not isinstance(text, str):
        text = str(text)

    # Replace literal \n with actual newlines and then replace all newlines with HTML breaks
    text = text.replace('\\n', '\n').replace('\n', '<br>')
    comment_id = f"{row_id}_comment"

    if len(text) <= 150:
        return text

    truncated = text[:150] + "..."

    # Use data-html="true" to ensure HTML tags are rendered in the tooltip
    return f'''<span class="comment-text"
                    onclick="showFullComment('{comment_id}')"
                    style="cursor:pointer; text-decoration:underline; color:#0d6efd;"
                    data-fulltext="{html.escape(text)}">
                {html.escape(truncated).replace('<br>', ' ')}
                </span>'''

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
