import os
import pandas as pd
import io
import json
import itertools
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "supersecretkey"  # For flash messages

# Create upload and result directories if they don't exist
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
RESULT_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULT_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['RESULT_FOLDER'] = RESULT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

ALLOWED_EXTENSIONS = {'csv'}

def create_hyperlink_for_ids(df, id_col="ID", additional_id_cols=None):
    """
    Create a copy of the dataframe with ID hyperlinks for web display.
    Does not modify the original dataframe.

    Parameters:
    - df: DataFrame to process
    - id_col: Primary ID column name
    - additional_id_cols: Additional ID columns to process (e.g., for merged dataframes)
    """
    import re
    df_copy = df.copy()

    # Process the main ID column
    if id_col in df_copy.columns:
        df_copy[id_col] = df_copy[id_col].astype(str).apply(
            lambda x: re.sub(
                r'\bT(\d+)\b',
                r'<a href="https://sonos.testrail.com/index.php?/tests/view/\1" target="_blank">T\1</a>',
                x
            )
        )

    # Process any additional ID columns
    if additional_id_cols:
        for col in additional_id_cols:
            if col in df_copy.columns:
                df_copy[col] = df_copy[col].astype(str).apply(
                    lambda x: re.sub(
                        r'\bT(\d+)\b',
                        r'<a href="https://sonos.testrail.com/index.php?/tests/view/\1" target="_blank">T\1</a>',
                        x
                    )
                )

    return df_copy

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Get all uploaded files and names
        files = request.files.getlist('files[]')
        file_names = request.form.getlist('file_names[]')

        # Check if enough files are provided (at least 2)
        if len(files) < 2:
            flash('At least two files are required for comparison', 'warning')
            return redirect(request.url)

        # Check if all files have names
        if len(file_names) != len(files):
            flash('All files must have names', 'warning')
            return redirect(request.url)

        # Check if all file names are provided and not empty
        if not all(file_names):
            flash('Names for all files are required', 'warning')
            return redirect(request.url)

        # Check if all files are selected
        if any(file.filename == '' for file in files):
            flash('All files must be selected', 'warning')
            return redirect(request.url)

        # Check if all files are valid CSV
        if not all(allowed_file(file.filename) for file in files):
            flash('Only CSV files are allowed', 'warning')
            return redirect(request.url)

        # Save files
        file_paths = []
        for i, file in enumerate(files):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
            file.save(filepath)
            file_paths.append(filepath)

        try:
            # Process the files and get both Excel file and comparison data
            result_file, comparison_data = process_csv_files(file_paths, file_names)

            # Save comparison data to a temporary JSON file
            json_filename = os.path.basename(result_file).replace('.xlsx', '.json')
            json_filepath = os.path.join(app.config['RESULT_FOLDER'], json_filename)

            with open(json_filepath, 'w') as f:
                json.dump(comparison_data, f)

            # Return results page
            return redirect(url_for('results', filename=os.path.basename(result_file),
                                    json_file=json_filename))
        except Exception as e:
            flash(f'Error processing files: {str(e)}', 'danger')
            return redirect(request.url)

    return render_template('index.html')

@app.route('/results/<filename>')
def results(filename):
    json_file = request.args.get('json_file')

    # Handle the case where json_file is None
    if json_file is None:
        flash('Error: Missing JSON data. Please upload files again.', 'danger')
        return redirect(url_for('index'))

    json_filepath = os.path.join(app.config['RESULT_FOLDER'], json_file)

    # Check if the JSON file exists
    if not os.path.exists(json_filepath):
        flash('Error: Result data not found. Please upload files again.', 'danger')
        return redirect(url_for('index'))

    # Load comparison data from JSON file
    try:
        with open(json_filepath, 'r') as f:
            comparison_data = json.load(f)

        # Convert string representations of DataFrames back to DataFrames for display
        data_for_display = {}
        for key, value in comparison_data.items():
            if key == 'summary' or key == 'file_names' or key == 'file_count' or key == 'matrix':
                data_for_display[key] = value
            else:
                if isinstance(value, str):  # Check if it's a string (JSON serialized DataFrame)
                    df = pd.read_json(value)
                    # Convert DataFrame to HTML table
                    data_for_display[key] = df.to_html(classes='table table-striped table-bordered table-hover',
                                                    index=False, escape=False)
                else:
                    # Handle nested structures (like dictionaries of DataFrames)
                    nested_data = {}
                    for nested_key, nested_value in value.items():
                        if isinstance(nested_value, str):
                            nested_df = pd.read_json(nested_value)
                            nested_data[nested_key] = nested_df.to_html(
                                classes='table table-striped table-bordered table-hover',
                                index=False, escape=False
                            )
                        else:
                            nested_data[nested_key] = nested_value
                    data_for_display[key] = nested_data

        return render_template('results.html', filename=filename, data=data_for_display)
    except json.JSONDecodeError:
        flash('Error: Failed to decode JSON data. Please upload files again.', 'danger')
        return redirect(url_for('index'))
    except Exception as e:
        flash(f'Error processing results: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/download/<filename>')
def download(filename):
    return send_file(os.path.join(app.config['RESULT_FOLDER'], filename), as_attachment=True)

@app.route('/direct-results/<filename>')
def direct_results(filename):
    """
    Alternative endpoint that loads Excel file directly by name.
    Useful for accessing results when JSON data is not available.
    """
    excel_path = os.path.join(app.config['RESULT_FOLDER'], filename)

    if not os.path.exists(excel_path):
        flash('Error: Result file not found.', 'danger')
        return redirect(url_for('index'))

    try:
        # Read the Excel file directly
        excel_data = {}

        # Read the Excel file to get file names and data
        xl = pd.ExcelFile(excel_path)
        sheet_names = xl.sheet_names

        # Try to extract file names from the sheets
        file_names = []
        for sheet in sheet_names:
            if sheet.startswith('All_Data_'):
                file_name = sheet.replace('All_Data_', '')
                if file_name not in file_names:
                    file_names.append(file_name)

        excel_data['file_names'] = file_names
        excel_data['file_count'] = len(file_names)

        # Create a summary based on sheet names
        summary = {}
        for sheet in sheet_names:
            if "_in_" in sheet and not sheet.startswith('All_'):
                key = sheet.replace('_', ' ')
                df = pd.read_excel(excel_path, sheet_name=sheet)
                summary[key] = len(df)

        # Add combined stats
        for sheet in sheet_names:
            if sheet.startswith('All_'):
                key = sheet.replace('_', ' ')
                df = pd.read_excel(excel_path, sheet_name=sheet)
                summary[key] = len(df)

        excel_data['summary'] = summary

        # Read the comparison matrix if it exists
        if 'Comparison_Matrix' in sheet_names:
            matrix_df = pd.read_excel(excel_path, sheet_name='Comparison_Matrix')
            matrix_data = matrix_df.to_dict(orient='records')
            excel_data['matrix'] = matrix_data

        # Read all the sheets
        for sheet in sheet_names:
            if not sheet.startswith('All_Data_') and sheet != 'Comparison_Matrix':  # Skip raw data sheets
                df = pd.read_excel(excel_path, sheet_name=sheet)

                # Apply hyperlinks to IDs
                if 'ID' in df.columns:
                    additional_cols = [col for col in df.columns if col.endswith(' ID')]
                    df = create_hyperlink_for_ids(df, "ID", additional_cols)

                key = sheet.lower()
                excel_data[key] = df.to_html(classes='table table-striped table-bordered table-hover',
                                            index=False, escape=False)

        # Now include the "All_Data" sheets for reference
        for sheet in sheet_names:
            if sheet.startswith('All_Data_'):
                df = pd.read_excel(excel_path, sheet_name=sheet)
                if 'ID' in df.columns:
                    df = create_hyperlink_for_ids(df, "ID")
                key = sheet.lower()
                excel_data[key] = df.to_html(classes='table table-striped table-bordered table-hover',
                                            index=False, escape=False)

        return render_template('results.html', filename=filename, data=excel_data)
    except Exception as e:
        flash(f'Error processing Excel file: {str(e)}', 'danger')
        return redirect(url_for('index'))

def process_csv_files(file_paths, file_names):
    """
    Process multiple CSV files and compare their test cases.
    Returns the path to the Excel file and the comparison data.

    Parameters:
    - file_paths: List of paths to the CSV files
    - file_names: List of names for the CSV files
    """
    # Columns to include in the output
    columns = ["ID", "Title", "Case ID", "Comment", "Plan", "Status", "Tested By"]

    # Load data from CSV files into a dictionary of dataframes
    file_data = {}
    for i, file_path in enumerate(file_paths):
        file_data[file_names[i]] = pd.read_csv(file_path)

    # Define functions for comparison
    def get_pass_fail(df):
        """Split a dataframe into passed and failed tests"""
        passed = df[df["Status"].str.lower() == "passed"]
        failed = df[df["Status"].str.lower() == "failed"]
        return passed, failed

    def filter_minor(df):
        """Filter tests with minor or bypass in comments"""
        return df[df["Comment"].str.contains(r"(?i)\b(minor|bypass)", case=False, na=False)]

    # Process each file to get passed, failed, and minor cases
    passed_data = {}
    failed_data = {}
    minor_data = {}
    case_id_sets = {}  # For storing sets of Case IDs by category

    for file_name, df in file_data.items():
        # Get passed and failed tests
        passed, failed = get_pass_fail(df)
        passed_data[file_name] = passed
        failed_data[file_name] = failed

        # Get minor cases
        minor = filter_minor(df)
        minor_data[file_name] = minor

        # Create sets of Case IDs
        case_id_sets[f"{file_name}_passed"] = set(passed["Case ID"])
        case_id_sets[f"{file_name}_failed"] = set(failed["Case ID"])
        case_id_sets[f"{file_name}_minor"] = set(minor["Case ID"])

    # Generate comparison sets for all possible file combinations
    comparisons = {
        "failed": {},
        "passed": {},
        "minor": {}
    }

    # Function to get all combinations of file names
    def get_file_combinations(file_list, r):
        return list(itertools.combinations(file_list, r))

    # For each file, find cases unique to that file
    for file_name in file_names:
        # Unique failed cases
        failed_in_this_file = case_id_sets[f"{file_name}_failed"]
        failed_in_other_files = set()
        for other_file in file_names:
            if other_file != file_name:
                failed_in_other_files.update(case_id_sets[f"{other_file}_failed"])

        unique_failed = failed_in_this_file - failed_in_other_files
        comparisons["failed"][f"{file_name}_only"] = failed_data[file_name][
            failed_data[file_name]["Case ID"].isin(unique_failed)
        ][columns]

        # Unique passed cases
        passed_in_this_file = case_id_sets[f"{file_name}_passed"]
        passed_in_other_files = set()
        for other_file in file_names:
            if other_file != file_name:
                passed_in_other_files.update(case_id_sets[f"{other_file}_passed"])

        unique_passed = passed_in_this_file - passed_in_other_files
        comparisons["passed"][f"{file_name}_only"] = passed_data[file_name][
            passed_data[file_name]["Case ID"].isin(unique_passed)
        ][columns]

        # Unique minor cases
        minor_in_this_file = case_id_sets[f"{file_name}_minor"]
        minor_in_other_files = set()
        for other_file in file_names:
            if other_file != file_name:
                minor_in_other_files.update(case_id_sets[f"{other_file}_minor"])

        unique_minor = minor_in_this_file - minor_in_other_files
        comparisons["minor"][f"{file_name}_only"] = minor_data[file_name][
            minor_data[file_name]["Case ID"].isin(unique_minor)
        ][columns]

    # Find intersections for each pair of files
    for i in range(2, len(file_names) + 1):
        file_combos = get_file_combinations(file_names, i)

        for combo in file_combos:
            combo_name = "_and_".join(combo)

            # Failed in all files in this combination
            failed_in_all = set.intersection(*[case_id_sets[f"{file}_failed"] for file in combo])
            failed_in_rest = set()
            for file in file_names:
                if file not in combo:
                    failed_in_rest.update(case_id_sets[f"{file}_failed"])
            unique_to_combo = failed_in_all - failed_in_rest

            if unique_to_combo:  # Only add if there are results
                # Use the first file's data as a base
                base_file = combo[0]
                comparisons["failed"][combo_name] = failed_data[base_file][
                    failed_data[base_file]["Case ID"].isin(unique_to_combo)
                ][columns]

            # Passed in all files in this combination
            passed_in_all = set.intersection(*[case_id_sets[f"{file}_passed"] for file in combo])
            passed_in_rest = set()
            for file in file_names:
                if file not in combo:
                    passed_in_rest.update(case_id_sets[f"{file}_passed"])
            unique_to_combo = passed_in_all - passed_in_rest

            if unique_to_combo:  # Only add if there are results
                # Use the first file's data as a base
                base_file = combo[0]
                comparisons["passed"][combo_name] = passed_data[base_file][
                    passed_data[base_file]["Case ID"].isin(unique_to_combo)
                ][columns]

            # Minor in all files in this combination
            minor_in_all = set.intersection(*[case_id_sets[f"{file}_minor"] for file in combo])
            minor_in_rest = set()
            for file in file_names:
                if file not in combo:
                    minor_in_rest.update(case_id_sets[f"{file}_minor"])
            unique_to_combo = minor_in_all - minor_in_rest

            if unique_to_combo:  # Only add if there are results
                # Use the first file's data as a base
                base_file = combo[0]
                comparisons["minor"][combo_name] = minor_data[base_file][
                    minor_data[base_file]["Case ID"].isin(unique_to_combo)
                ][columns]

    # Special case: Find cases that are in all files
    if len(file_names) > 1:
        # Failed in all files
        failed_in_all_files = set.intersection(*[case_id_sets[f"{file}_failed"] for file in file_names])
        if failed_in_all_files:
            comparisons["failed"]["all_files"] = failed_data[file_names[0]][
                failed_data[file_names[0]]["Case ID"].isin(failed_in_all_files)
            ][columns]

        # Passed in all files
        passed_in_all_files = set.intersection(*[case_id_sets[f"{file}_passed"] for file in file_names])
        if passed_in_all_files:
            comparisons["passed"]["all_files"] = passed_data[file_names[0]][
                passed_data[file_names[0]]["Case ID"].isin(passed_in_all_files)
            ][columns]

        # Minor in all files
        minor_in_all_files = set.intersection(*[case_id_sets[f"{file}_minor"] for file in file_names])
        if minor_in_all_files:
            comparisons["minor"]["all_files"] = minor_data[file_names[0]][
                minor_data[file_names[0]]["Case ID"].isin(minor_in_all_files)
            ][columns]

    # Write results to Excel file
    output_filename = 'multi_case_comparison_result.xlsx'
    output_path = os.path.join(app.config['RESULT_FOLDER'], output_filename)

    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        # Write original file data
        for file_name, df in file_data.items():
            df.to_excel(writer, sheet_name=f"All_Data_{file_name}", index=False)

        # Write all failed, passed, and minor data
        for file_name in file_names:
            failed_data[file_name][columns].to_excel(writer, sheet_name=f"All_Failed_{file_name}", index=False)
            passed_data[file_name][columns].to_excel(writer, sheet_name=f"All_Passed_{file_name}", index=False)
            minor_data[file_name][columns].to_excel(writer, sheet_name=f"All_Minor_{file_name}", index=False)

        # Write comparison results
        for category, category_comparisons in comparisons.items():
            for name, df in category_comparisons.items():
                sheet_name = f"{category.capitalize()}_in_{name}"
                # Truncate sheet name if too long (Excel has 31 character limit)
                if len(sheet_name) > 31:
                    sheet_name = sheet_name[:28] + "..."
                df.to_excel(writer, sheet_name=sheet_name, index=False)

        # Create and write comparison matrix
        matrix_data = create_comparison_matrix(case_id_sets, file_names)
        matrix_df = pd.DataFrame(matrix_data)
        matrix_df.to_excel(writer, sheet_name="Comparison_Matrix", index=False)

    # Generate summary statistics
    summary = {}

    # Add file counts
    for file_name in file_names:
        summary[f"Total cases in {file_name}"] = len(file_data[file_name])
        summary[f"Failed cases in {file_name}"] = len(failed_data[file_name])
        summary[f"Passed cases in {file_name}"] = len(passed_data[file_name])
        summary[f"Minor cases in {file_name}"] = len(minor_data[file_name])

    # Add comparison counts
    for category, category_comparisons in comparisons.items():
        for name, df in category_comparisons.items():
            summary[f"{category.capitalize()} in {name}"] = len(df)

    # Prepare hyperlinked DataFrames for web display
    web_comparisons = {
        "failed": {},
        "passed": {},
        "minor": {}
    }

    for category, category_comparisons in comparisons.items():
        for name, df in category_comparisons.items():
            web_comparisons[category][name] = create_hyperlink_for_ids(df, "ID").to_json(orient='records')

    # Prepare data for all files with hyperlinks
    all_data_web = {}
    for file_name in file_names:
        all_failed = create_hyperlink_for_ids(failed_data[file_name][columns], "ID")
        all_passed = create_hyperlink_for_ids(passed_data[file_name][columns], "ID")
        all_minor = create_hyperlink_for_ids(minor_data[file_name][columns], "ID")

        all_data_web[f"all_failed_{file_name}"] = all_failed.to_json(orient='records')
        all_data_web[f"all_passed_{file_name}"] = all_passed.to_json(orient='records')
        all_data_web[f"all_minor_{file_name}"] = all_minor.to_json(orient='records')

    # Create a dictionary with all comparison data
    comparison_data = {
        "summary": summary,
        "file_names": file_names,
        "file_count": len(file_names),
        "matrix": matrix_data,
        "failed_comparisons": web_comparisons["failed"],
        "passed_comparisons": web_comparisons["passed"],
        "minor_comparisons": web_comparisons["minor"],
        "all_data": all_data_web
    }

    return output_path, comparison_data

def create_comparison_matrix(case_id_sets, file_names):
    """
    Create a matrix showing overlap of cases between files.

    Parameters:
    - case_id_sets: Dictionary containing sets of Case IDs for each file and category
    - file_names: List of file names

    Returns:
    - List of dictionaries for the comparison matrix
    """
    matrix_data = []

    # For each pair of files, calculate the overlap
    for i, file1 in enumerate(file_names):
        for j, file2 in enumerate(file_names[i:], i):
            # Skip comparing a file to itself
            if file1 == file2 and i == j:
                continue

            # Calculate intersection sizes
            failed_intersection = len(case_id_sets[f"{file1}_failed"] & case_id_sets[f"{file2}_failed"])
            passed_intersection = len(case_id_sets[f"{file1}_passed"] & case_id_sets[f"{file2}_passed"])
            minor_intersection = len(case_id_sets[f"{file1}_minor"] & case_id_sets[f"{file2}_minor"])

            # Calculate union sizes (for Jaccard similarity)
            failed_union = len(case_id_sets[f"{file1}_failed"] | case_id_sets[f"{file2}_failed"])
            passed_union = len(case_id_sets[f"{file1}_passed"] | case_id_sets[f"{file2}_passed"])
            minor_union = len(case_id_sets[f"{file1}_minor"] | case_id_sets[f"{file2}_minor"])

            # Calculate Jaccard similarity (intersection / union)
            failed_jaccard = failed_intersection / failed_union if failed_union > 0 else 0
            passed_jaccard = passed_intersection / passed_union if passed_union > 0 else 0
            minor_jaccard = minor_intersection / minor_union if minor_union > 0 else 0

            # Add to matrix data
            matrix_data.append({
                "File 1": file1,
                "File 2": file2,
                "Failed Overlap": failed_intersection,
                "Failed Jaccard": round(failed_jaccard, 3),
                "Passed Overlap": passed_intersection,
                "Passed Jaccard": round(passed_jaccard, 3),
                "Minor Overlap": minor_intersection,
                "Minor Jaccard": round(minor_jaccard, 3)
            })

    return matrix_data

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
