import subprocess
import os

def run_restore():
    sql_file = "/home/sylendra/clean_data.sql"

    if not os.path.exists(sql_file):
        print(f"❌ File not found: {sql_file}")
        return

    print("🚀 Starting SQL restore from clean_data.sql...\n")

    cmd = [
        "psql",
        "-h", "34.23.138.181",
        "-U", "sylendrar",
        "-d", "ticketing_genie",
        "-f", sql_file
    ]

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n✅ Restore completed successfully")
    else:
        print("\n❌ Restore failed")


if __name__ == "__main__":
    run_restore()