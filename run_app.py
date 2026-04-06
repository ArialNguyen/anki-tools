# File: run_app.py
import json
import sys

from modules import VocabEnricher

def load_config(config_path="config.json"):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit(f"❌ LỖI: Không tìm thấy file {config_path}! Vui lòng tạo file cấu hình.")
    except json.JSONDecodeError:
        sys.exit(f"❌ LỖI: File {config_path} sai cú pháp JSON.")

if __name__ == "__main__":
    app_config = load_config("config.json")
    
    engine = VocabEnricher(env_path=".env", config=app_config)
    engine.run(
        relative_source_path="../Vocab_mountain_Writting.xlsm",
        sheet_name="Day 8",
        output_csv_name="day8_anki.csv"
    ) 