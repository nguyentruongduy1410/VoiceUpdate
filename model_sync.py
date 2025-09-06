"""
Model Sync Manager - Đồng bộ models từ Google Drive

Chức năng:
- Kiểm tra phiên bản models từ Google Drive
- Tải về models mới khi có cập nhật
- Quản lý cache và backup models
- Hỗ trợ resume download khi bị gián đoạn
"""

import os
import sys
import json
import shutil
import hashlib
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
import requests
from PyQt5.QtCore import QObject, pyqtSignal, QThread
from PyQt5.QtWidgets import QMessageBox, QProgressDialog, QApplication
import zipfile


class ModelDownloader(QObject):
    """Downloader cho models từ Google Drive"""
    
    # Signals
    download_progress = pyqtSignal(int)      # Progress (0-100)
    download_status = pyqtSignal(str)        # Status message
    download_completed = pyqtSignal(str)     # File path khi hoàn thành
    download_error = pyqtSignal(str)         # Error message
    
    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'VoiceApp-ModelSync/1.0'
        })
    
    def get_google_drive_direct_url(self, drive_url: str) -> str:
        """Chuyển đổi Google Drive sharing URL thành direct download URL"""
        if 'drive.google.com' in drive_url:
            # Extract file ID từ URL
            if '/file/d/' in drive_url:
                file_id = drive_url.split('/file/d/')[1].split('/')[0]
            elif 'id=' in drive_url:
                file_id = drive_url.split('id=')[1].split('&')[0]
            else:
                return drive_url
            
            # Trả về direct download URL
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        
        return drive_url
    
    def get_file_size(self, url: str) -> int:
        """Lấy kích thước file từ URL"""
        try:
            response = self.session.head(url, allow_redirects=True, timeout=30)
            if response.status_code == 200:
                content_length = response.headers.get('content-length')
                if content_length:
                    return int(content_length)
        except Exception:
            pass
        return 0
    
    def download_file(self, url: str, local_path: str, resume: bool = True) -> bool:
        """Tải file với hỗ trợ resume"""
        try:
            # Chuyển đổi Google Drive URL
            direct_url = self.get_google_drive_direct_url(url)
            
            # Kiểm tra file size
            total_size = self.get_file_size(direct_url)
            
            # Kiểm tra file đã tồn tại (cho resume)
            headers = {}
            initial_pos = 0
            
            if resume and os.path.exists(local_path):
                initial_pos = os.path.getsize(local_path)
                if initial_pos > 0:
                    headers['Range'] = f'bytes={initial_pos}-'
                    self.download_status.emit(f"Tiếp tục tải từ {initial_pos} bytes...")
            
            # Tạo thư mục nếu chưa có
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            # Bắt đầu download
            response = self.session.get(direct_url, headers=headers, stream=True, timeout=30)
            
            # Xử lý Google Drive confirmation page
            if 'text/html' in response.headers.get('content-type', ''):
                # Tìm confirmation link
                content = response.text
                if 'download_warning' in content:
                    import re
                    confirm_pattern = r'href="(/uc\?export=download[^"]*)"'
                    match = re.search(confirm_pattern, content)
                    if match:
                        confirm_url = 'https://drive.google.com' + match.group(1)
                        response = self.session.get(confirm_url, stream=True, timeout=30)
            
            response.raise_for_status()
            
            # Mở file để ghi (append mode nếu resume)
            mode = 'ab' if resume and initial_pos > 0 else 'wb'
            
            downloaded_size = initial_pos
            chunk_size = 8192
            
            with open(local_path, mode) as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # Cập nhật progress
                        if total_size > 0:
                            progress = int((downloaded_size / total_size) * 100)
                            self.download_progress.emit(progress)
                        
                        # Cập nhật status
                        if downloaded_size % (1024 * 1024) == 0:  # Mỗi MB
                            size_mb = downloaded_size / (1024 * 1024)
                            total_mb = total_size / (1024 * 1024) if total_size > 0 else 0
                            if total_mb > 0:
                                self.download_status.emit(f"Đã tải: {size_mb:.1f}MB / {total_mb:.1f}MB")
                            else:
                                self.download_status.emit(f"Đã tải: {size_mb:.1f}MB")
            
            self.download_completed.emit(local_path)
            return True
            
        except Exception as e:
            error_msg = f"Lỗi tải file: {str(e)}"
            self.download_error.emit(error_msg)
            return False
    
    def verify_file_integrity(self, file_path: str, expected_hash: str = None) -> bool:
        """Kiểm tra tính toàn vẹn file"""
        if not os.path.exists(file_path):
            return False
        
        if expected_hash:
            try:
                sha256_hash = hashlib.sha256()
                with open(file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        sha256_hash.update(chunk)
                
                file_hash = sha256_hash.hexdigest()
                return file_hash.lower() == expected_hash.lower()
            except Exception:
                return False
        
        # Nếu không có hash để so sánh, chỉ kiểm tra file có tồn tại và có size > 0
        return os.path.getsize(file_path) > 0


class ModelSyncManager(QObject):
    """Manager chính để đồng bộ models"""
    
    # Signals
    sync_started = pyqtSignal()
    sync_completed = pyqtSignal()
    sync_progress = pyqtSignal(int, str)  # progress, status
    sync_error = pyqtSignal(str)
    model_updated = pyqtSignal(str)       # model name
    
    def __init__(self, config_file: str = None):
        super().__init__()
        
        # Đường dẫn thư mục
        self.app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.models_dir = os.path.join(self.app_dir, "models")
        self.secure_models_dir = os.path.join(self.app_dir, "secure_models")
        self.cache_dir = os.path.join(self.app_dir, ".cache", "models")
        
        # Tạo thư mục nếu chưa có
        os.makedirs(self.models_dir, exist_ok=True)
        os.makedirs(self.secure_models_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # File cấu hình
        self.config_file = config_file or os.path.join(self.app_dir, "model_sync_config.json")
        self.version_file = os.path.join(self.cache_dir, "model_versions.json")
        self.last_sync_file = os.path.join(self.cache_dir, "last_sync.json")
        
        # Tải cấu hình
        self.config = self.load_config()
        
        # Downloader
        self.downloader = ModelDownloader()
        self.downloader.download_progress.connect(lambda p: self.sync_progress.emit(p, ""))
        self.downloader.download_status.connect(lambda s: self.sync_progress.emit(-1, s))
        self.downloader.download_error.connect(self.sync_error.emit)
    
    def load_config(self) -> Dict[str, Any]:
        """Tải cấu hình từ file"""
        default_config = {
            "models": {
                "vocos_model": {
                    "url": "",
                    "version": "1.0.0",
                    "type": "zip",
                    "destination": "models/vocos_model",
                    "files": ["config.yaml", "pytorch_model.bin"],
                    "hash": ""
                },
                "whisper_medium": {
                    "url": "",
                    "version": "1.0.0", 
                    "type": "file",
                    "destination": "models/whisper",
                    "filename": "medium.pt",
                    "hash": ""
                },
                "secure_model": {
                    "url": "",
                    "version": "1.0.0",
                    "type": "file",
                    "destination": "secure_models",
                    "filename": "model.enc",
                    "hash": ""
                },
                "secure_vocab": {
                    "url": "",
                    "version": "1.0.0",
                    "type": "file", 
                    "destination": "secure_models",
                    "filename": "vocab.enc",
                    "hash": ""
                }
            },
            "check_interval_hours": 24,
            "auto_update": True,
            "backup_old_models": True
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # Merge với default config
                    return {**default_config, **config}
        except Exception:
            pass
        
        # Tạo file config mặc định
        self.save_config(default_config)
        return default_config
    
    def save_config(self, config: Dict[str, Any]):
        """Lưu cấu hình ra file"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Lỗi lưu config: {e}")
    
    def get_model_versions(self) -> Dict[str, str]:
        """Lấy version của các models hiện tại"""
        try:
            if os.path.exists(self.version_file):
                with open(self.version_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}
    
    def save_model_versions(self, versions: Dict[str, str]):
        """Lưu version của các models"""
        try:
            with open(self.version_file, 'w', encoding='utf-8') as f:
                json.dump(versions, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Lỗi lưu model versions: {e}")
    
    def check_for_model_updates(self) -> List[str]:
        """Kiểm tra models nào cần cập nhật"""
        current_versions = self.get_model_versions()
        models_to_update = []
        
        for model_name, model_config in self.config["models"].items():
            current_version = current_versions.get(model_name, "0.0.0")
            remote_version = model_config.get("version", "1.0.0")
            
            if self.compare_versions(remote_version, current_version) > 0:
                models_to_update.append(model_name)
        
        return models_to_update
    
    def compare_versions(self, version1: str, version2: str) -> int:
        """So sánh 2 version"""
        try:
            v1_parts = [int(x) for x in version1.split('.')]
            v2_parts = [int(x) for x in version2.split('.')]
            
            # Đảm bảo cùng độ dài
            max_len = max(len(v1_parts), len(v2_parts))
            v1_parts.extend([0] * (max_len - len(v1_parts)))
            v2_parts.extend([0] * (max_len - len(v2_parts)))
            
            for i in range(max_len):
                if v1_parts[i] > v2_parts[i]:
                    return 1
                elif v1_parts[i] < v2_parts[i]:
                    return -1
            
            return 0
        except Exception:
            return 0
    
    def backup_model(self, model_name: str) -> bool:
        """Backup model hiện tại"""
        if not self.config.get("backup_old_models", True):
            return True
        
        try:
            model_config = self.config["models"][model_name]
            dest_path = os.path.join(self.app_dir, model_config["destination"])
            
            if not os.path.exists(dest_path):
                return True
            
            # Tạo backup với timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = os.path.join(self.cache_dir, "backups", model_name, timestamp)
            os.makedirs(backup_dir, exist_ok=True)
            
            if os.path.isfile(dest_path):
                shutil.copy2(dest_path, backup_dir)
            else:
                shutil.copytree(dest_path, os.path.join(backup_dir, os.path.basename(dest_path)))
            
            return True
            
        except Exception as e:
            print(f"Lỗi backup model {model_name}: {e}")
            return False
    
    def download_model(self, model_name: str) -> bool:
        """Tải về một model"""
        try:
            model_config = self.config["models"][model_name]
            url = model_config.get("url")
            
            if not url:
                self.sync_error.emit(f"Không có URL cho model {model_name}")
                return False
            
            # Backup model cũ
            self.sync_progress.emit(-1, f"Đang backup {model_name}...")
            self.backup_model(model_name)
            
            # Đường dẫn tải về
            if model_config["type"] == "file":
                filename = model_config.get("filename", f"{model_name}.bin")
                temp_path = os.path.join(self.cache_dir, "downloads", filename)
            else:
                temp_path = os.path.join(self.cache_dir, "downloads", f"{model_name}.zip")
            
            # Tạo thư mục download
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)
            
            # Tải về
            self.sync_progress.emit(-1, f"Đang tải {model_name}...")
            success = self.downloader.download_file(url, temp_path)
            
            if not success:
                return False
            
            # Kiểm tra tính toàn vẹn
            expected_hash = model_config.get("hash")
            if expected_hash:
                self.sync_progress.emit(-1, f"Đang kiểm tra {model_name}...")
                if not self.downloader.verify_file_integrity(temp_path, expected_hash):
                    self.sync_error.emit(f"File {model_name} bị hỏng hoặc không đúng")
                    return False
            
            # Cài đặt model
            self.sync_progress.emit(-1, f"Đang cài đặt {model_name}...")
            if not self.install_model(model_name, temp_path):
                return False
            
            # Cập nhật version
            current_versions = self.get_model_versions()
            current_versions[model_name] = model_config["version"]
            self.save_model_versions(current_versions)
            
            self.model_updated.emit(model_name)
            return True
            
        except Exception as e:
            error_msg = f"Lỗi tải model {model_name}: {str(e)}"
            self.sync_error.emit(error_msg)
            return False
    
    def install_model(self, model_name: str, temp_path: str) -> bool:
        """Cài đặt model từ file đã tải về"""
        try:
            model_config = self.config["models"][model_name]
            dest_dir = os.path.join(self.app_dir, model_config["destination"])
            
            # Tạo thư mục đích
            os.makedirs(dest_dir, exist_ok=True)
            
            if model_config["type"] == "file":
                # Copy file trực tiếp
                filename = model_config.get("filename", os.path.basename(temp_path))
                dest_path = os.path.join(dest_dir, filename)
                shutil.copy2(temp_path, dest_path)
                
            elif model_config["type"] == "zip":
                # Giải nén
                with zipfile.ZipFile(temp_path, 'r') as zip_ref:
                    zip_ref.extractall(dest_dir)
            
            return True
            
        except Exception as e:
            print(f"Lỗi cài đặt model {model_name}: {e}")
            return False
    
    def sync_models_async(self, models_to_sync: List[str] = None):
        """Đồng bộ models trong background thread"""
        def sync_thread():
            self.sync_started.emit()
            
            try:
                if models_to_sync is None:
                    # Kiểm tra tất cả models
                    models_to_sync_list = self.check_for_model_updates()
                else:
                    models_to_sync_list = models_to_sync
                
                if not models_to_sync_list:
                    self.sync_progress.emit(100, "Tất cả models đã cập nhật")
                    self.sync_completed.emit()
                    return
                
                total_models = len(models_to_sync_list)
                
                for i, model_name in enumerate(models_to_sync_list):
                    overall_progress = int((i / total_models) * 100)
                    self.sync_progress.emit(overall_progress, f"Đang xử lý {model_name}...")
                    
                    success = self.download_model(model_name)
                    if not success:
                        # Tiếp tục với model khác nếu có lỗi
                        continue
                
                # Lưu thông tin sync cuối cùng
                self.save_last_sync_info()
                
                self.sync_progress.emit(100, "Hoàn thành đồng bộ models")
                self.sync_completed.emit()
                
            except Exception as e:
                error_msg = f"Lỗi đồng bộ models: {str(e)}"
                self.sync_error.emit(error_msg)
        
        thread = threading.Thread(target=sync_thread, daemon=True)
        thread.start()
    
    def save_last_sync_info(self):
        """Lưu thông tin sync cuối cùng"""
        sync_info = {
            "timestamp": datetime.now().isoformat(),
            "models_synced": list(self.config["models"].keys()),
            "success": True
        }
        
        try:
            with open(self.last_sync_file, 'w', encoding='utf-8') as f:
                json.dump(sync_info, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    
    def should_auto_sync(self) -> bool:
        """Kiểm tra có nên auto sync không"""
        if not self.config.get("auto_update", True):
            return False
        
        try:
            if os.path.exists(self.last_sync_file):
                with open(self.last_sync_file, 'r', encoding='utf-8') as f:
                    last_sync = json.load(f)
                    
                last_sync_time = datetime.fromisoformat(last_sync["timestamp"])
                interval_hours = self.config.get("check_interval_hours", 24)
                
                if datetime.now() - last_sync_time < timedelta(hours=interval_hours):
                    return False
        except Exception:
            pass
        
        return True
    
    def cleanup_cache(self, max_age_days: int = 7):
        """Dọn dẹp cache cũ"""
        try:
            downloads_dir = os.path.join(self.cache_dir, "downloads")
            if os.path.exists(downloads_dir):
                cutoff_time = time.time() - (max_age_days * 24 * 60 * 60)
                
                for file in os.listdir(downloads_dir):
                    file_path = os.path.join(downloads_dir, file)
                    if os.path.getctime(file_path) < cutoff_time:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                        else:
                            shutil.rmtree(file_path, ignore_errors=True)
        except Exception:
            pass


def create_model_sync_manager(config_file: str = None) -> ModelSyncManager:
    """Tạo ModelSyncManager instance"""
    return ModelSyncManager(config_file)


if __name__ == "__main__":
    # Test
    import sys
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    manager = create_model_sync_manager()
    
    # Test kiểm tra update
    updates = manager.check_for_model_updates()
    print(f"Models cần cập nhật: {updates}")
    
    if updates:
        manager.sync_models_async(updates)
    
    sys.exit(app.exec_())
