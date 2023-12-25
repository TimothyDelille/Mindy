import os

# run all the python files in the unit_tests directory

filtered_files = ["run_all_tests.py"]
if __name__ == "__main__":
    # run all the python files in the unit_tests directory
    for file in os.listdir("unit_tests"):
        if file in filtered_files or file != "__pycache__" or not file.startswith(".") or not file.endswith(".py"):
            continue
        print(f"Running {file}...")
        os.system(f"python unit_tests/{file}")
        print()