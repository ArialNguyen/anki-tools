# 2. LOGIC QUẢN LÝ QUOTA CỦA TỪNG MODEL
# ==========================================
from datetime import datetime
import json
import os
import time
import threading
from rich.console import Console

console = Console()

class ModelRateTracker:
    def __init__(self, limit_rpm, limit_tpm, limit_rpd, saved_data):
        self.limit_rpm = limit_rpm
        self.limit_tpm = limit_tpm
        self.limit_rpd = limit_rpd
        
        # Hỗ trợ cả định dạng cũ (chỉ lưu mỗi số RPD) và định dạng mới (lưu Full)
        if isinstance(saved_data, int):
            self.rpd_count = saved_data
            self.rpm_window, self.tpm_window = [], []
        else:
            self.rpd_count = saved_data.get("rpd", 0)
            self.rpm_window = saved_data.get("rpm_window", [])  
            self.tpm_window = saved_data.get("tpm_window", [])

    def is_available(self, current_time):
        if self.rpd_count >= self.limit_rpd: return False
        
        # Xóa các request cũ hơn 75s (Dùng 75 thay vì 60 để an toàn)
        self.rpm_window = [t for t in self.rpm_window if current_time - t < 75]
        self.tpm_window = [item for item in self.tpm_window if current_time - item[0] < 75]
        
        if len(self.rpm_window) >= self.limit_rpm - 1: return False
        if sum(i[1] for i in self.tpm_window) >= self.limit_tpm - 1000: return False
        return True

    def pre_register(self, current_time):
        """Giữ chỗ trước khi gọi API để tránh các thread khác giành giật"""
        self.rpm_window.append(current_time)
        self.tpm_window.append([current_time, 1000]) # Ước tính trước 1000 token

    def record_actual_usage(self, current_time, actual_tokens):
        """Cập nhật lại số token thực tế sau khi API trả kết quả"""
        if self.tpm_window: 
            self.tpm_window[-1] = [current_time, actual_tokens]
        self.rpd_count += 1

    def to_dict(self):
        """Đóng gói để save ra file json"""
        current_time = time.time()
        self.rpm_window = [t for t in self.rpm_window if current_time - t < 75]
        self.tpm_window = [item for item in self.tpm_window if current_time - item[0] < 75]
        return {
            "rpd": self.rpd_count, 
            "rpm_window": self.rpm_window, 
            "tpm_window": self.tpm_window
        }
    
class KeyManager:
    def __init__(self, keys_info, base_dir, config):
        self.keys_info = keys_info 
        self.config = config
        self.lock = threading.Lock()
        
        self.tracker_file = os.path.join(base_dir, "rpd_tracker.json")
        self.today_str = datetime.now().strftime("%Y-%m-%d")
        self.rpd_data = self._load_rpd()
        if self.today_str not in self.rpd_data: 
            self.rpd_data = {self.today_str: {}}
            
        self.model_names_list = list(self.config["MODELS_CONFIG"].keys())
        self.active_model_display = {var_name: "Waiting..." for var_name, _ in keys_info}
        self.trackers = {}
        
        for var_name, _ in keys_info:
            if var_name not in self.rpd_data[self.today_str]:
                self.rpd_data[self.today_str][var_name] = {}
            self.trackers[var_name] = {}
            for m_name, m_cfg in self.config["MODELS_CONFIG"].items():
                saved_data = self.rpd_data[self.today_str][var_name].get(m_name, {})
                # Cần đảm bảo bạn đã import/khai báo ModelRateTracker ở trên
                self.trackers[var_name][m_name] = ModelRateTracker(m_cfg["RPM"], m_cfg["TPM"], m_cfg["RPD"], saved_data)

        base_cd = self.config["API_KEY_COOLDOWN"]
        self.current_cd = {var_name: float(base_cd) for var_name, _ in keys_info}
        self.cooldown_until = {var_name: 0.0 for var_name, _ in keys_info}
        self.stats = {var_name: {'total': 0, 'success': 0} for var_name, _ in keys_info}
        self.recent_durations = {var_name: [] for var_name, _ in keys_info}
        
        # Giữ lại 2 biến này gán bằng 0 để class DashboardUI đọc không bị lỗi (do đã bỏ thuật toán ban)
        self.consecutive_429 = {var_name: 0 for var_name, _ in keys_info}
        self.ui_ban_until = {var_name: 0.0 for var_name, _ in keys_info}

    def _load_rpd(self):
        if os.path.exists(self.tracker_file):
            try:
                with open(self.tracker_file, "r") as f: return json.load(f)
            except: pass
        return {}

    def _save_rpd(self):
        try:
            for var_name, _ in self.keys_info:
                for m_name in self.model_names_list:
                    self.rpd_data[self.today_str][var_name][m_name] = self.trackers[var_name][m_name].to_dict()
            with open(self.tracker_file, "w") as f: 
                json.dump(self.rpd_data, f, indent=4)
        except: pass

    def get_next_key_model(self):
        while True:
            with self.lock:
                current_time = time.time()
                all_exhausted = True
                for v_name, _ in self.keys_info:
                    for m_name in self.model_names_list:
                        if self.trackers[v_name][m_name].rpd_count < self.trackers[v_name][m_name].limit_rpd:
                            all_exhausted = False
                            break
                    if not all_exhausted: break
                        
                if all_exhausted:
                    console.print("\n🛑 [bold red]HẾT QUOTA! TOÀN BỘ KEYS ĐÃ CẠN SẠCH TẤT CẢ MODELS HÔM NAY![/]")
                    os._exit(1)

                selected_var, selected_key, selected_model = None, None, None
                for var_name, key in self.keys_info:
                    if current_time < self.cooldown_until[var_name]: continue
                    for m_name in self.model_names_list:
                        if self.trackers[var_name][m_name].is_available(current_time):
                            selected_var, selected_key, selected_model = var_name, key, m_name
                            break
                    if selected_var: break

                if selected_var:
                    self.trackers[selected_var][selected_model].pre_register(current_time)
                    self.cooldown_until[selected_var] = current_time + self.current_cd[selected_var]
                    self.active_model_display[selected_var] = selected_model
                    self._save_rpd()
                    return selected_var, selected_key, selected_model
            time.sleep(0.5)

    def record_success(self, var_name, model_name, duration, tokens):
        with self.lock:
            current_time = time.time()
            self.stats[var_name]['success'] += 1
            
            self.recent_durations[var_name].append(min(duration, 60.0))
            if len(self.recent_durations[var_name]) > 3: 
                self.recent_durations[var_name].pop(0)
                
            durs = self.recent_durations[var_name]
            n = len(durs)
            if n == 3: self.current_cd[var_name] = (durs[0] + durs[1]*2 + durs[2]*3) / 6.0
            elif n == 2: self.current_cd[var_name] = (durs[0] + durs[1]*2) / 3.0
            else: self.current_cd[var_name] = durs[0]
                
            self.trackers[var_name][model_name].record_actual_usage(current_time, tokens)
            self._save_rpd()

    def penalize_key(self, var_name):
        with self.lock:
            # 1. Tăng số đếm gậy 429
            self.consecutive_429[var_name] += 1
            
            # 2. Thuật toán Phạt lũy tiến (Lần 1 phạt 5s, lần 2 phạt 10s, tối đa 60s)
            backoff_time = min(60.0, 5.0 * (2 ** (self.consecutive_429[var_name] - 1)))
            target_time = time.time() + backoff_time
            
            # 3. Khóa Key này lại, không cho get_next_key_model() bốc trúng nó nữa
            self.cooldown_until[var_name] = target_time
            self.ui_ban_until[var_name] = target_time
            
            # Reset chuỗi thành công
            if hasattr(self, 'consecutive_successes'):
                self.consecutive_successes[var_name] = 0
            
    def record_attempt(self, var_name):
        with self.lock: 
            self.stats[var_name]['total'] += 1
