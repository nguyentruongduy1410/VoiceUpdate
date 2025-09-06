"""
Update Manager - Quản lý cập nhật từ GitHub Releases

Chức năng:
- Kiểm tra phiên bản mới từ GitHub Releases
- Tải về và cài đặt bản cập nhật
- Backup và restore khi cần
- Thông báo tiến trình cho người dùng
"""

import os
import sys
import json
import shutil
import tempfile
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Callable
import requests
from PyQt5.QtCore import QObject, pyqtSignal, QThread
from PyQt5.QtWidgets import QMessageBox, QProgressDialog, QApplication
import zipfile
import hashlib


class UpdateChecker(QObject):
    """Thread-safe update checker"""
    
    # Signals
    update_available = pyqtSignal(dict)  # Emit khi có update
    update_downloaded = pyqtSignal(str)  # Emit khi download xong
    progress_updated = pyqtSignal(int)   # Emit progress (0-100)
    status_updated = pyqtSignal(str)     # Emit status message
    error_occurred = pyqtSignal(str)     # Emit khi có lỗi
    
    def __init__(self, repo_owner: str, repo_name: str, current_version: str):
        super().__init__()
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.current_version = current_version
        self.github_api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        
        # Thư mục lưu cache và backup
        self.app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.cache_dir = os.path.join(self.app_dir, ".cache")
        self.backup_dir = os.path.join(self.app_dir, ".backup")
        
        # Tạo thư mục nếu chưa có
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)
        
        # File lưu thông tin update
        self.update_info_file = os.path.join(self.cache_dir, "update_info.json")
        self.last_check_file = os.path.join(self.cache_dir, "last_check.json")
    
    def get_latest_release(self) -> Optional[Dict[str, Any]]:
        """Lấy thông tin release mới nhất từ GitHub"""
        try:
            self.status_updated.emit("Đang kiểm tra phiên bản mới...")
            
            url = f"{self.github_api_url}/releases/latest"
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "VoiceApp-Updater/1.0"
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            release_data = response.json()
            
            # Lưu thông tin kiểm tra cuối cùng
            self.save_last_check(release_data)
            
            return release_data
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Lỗi kết nối GitHub: {str(e)}"
            self.error_occurred.emit(error_msg)
            return None
        except Exception as e:
            error_msg = f"Lỗi không xác định: {str(e)}"
            self.error_occurred.emit(error_msg)
            return None
    
    def compare_versions(self, version1: str, version2: str) -> int:
        """So sánh 2 version. Return: 1 nếu version1 > version2, -1 nếu ngược lại, 0 nếu bằng nhau"""
        try:
            # Loại bỏ 'v' prefix nếu có
            v1 = version1.lstrip('v').split('.')
            v2 = version2.lstrip('v').split('.')
            
            # Đảm bảo cùng độ dài
            max_len = max(len(v1), len(v2))
            v1.extend(['0'] * (max_len - len(v1)))
            v2.extend(['0'] * (max_len - len(v2)))
            
            for i in range(max_len):
                try:
                    n1 = int(v1[i])
                    n2 = int(v2[i])
                    if n1 > n2:
                        return 1
                    elif n1 < n2:
                        return -1
                except ValueError:
                    # Nếu không phải số, so sánh string
                    if v1[i] > v2[i]:
                        return 1
                    elif v1[i] < v2[i]:
                        return -1
            
            return 0
            
        except Exception:
            return 0
    
    def check_for_updates(self) -> bool:
        """Kiểm tra có update không"""
        release_data = self.get_latest_release()
        if not release_data:
            return False
        
        latest_version = release_data.get('tag_name', '').lstrip('v')
        current_version = self.current_version.lstrip('v')
        
        if self.compare_versions(latest_version, current_version) > 0:
            self.update_available.emit(release_data)
            return True
        
        self.status_updated.emit("Bạn đang sử dụng phiên bản mới nhất")
        return False
    
    def download_update(self, release_data: Dict[str, Any]) -> Optional[str]:
        """Tải về file update"""
        try:
            # Tìm asset phù hợp (file .exe hoặc .zip)
            assets = release_data.get('assets', [])
            download_asset = None
            
            for asset in assets:
                name = asset.get('name', '').lower()
                if name.endswith('.exe') or name.endswith('.zip'):
                    download_asset = asset
                    break
            
            if not download_asset:
                self.error_occurred.emit("Không tìm thấy file cập nhật phù hợp")
                return None
            
            download_url = download_asset.get('browser_download_url')
            file_name = download_asset.get('name')
            file_size = download_asset.get('size', 0)
            
            if not download_url:
                self.error_occurred.emit("Không tìm thấy URL tải về")
                return None
            
            # Đường dẫn file tải về
            download_path = os.path.join(self.cache_dir, file_name)
            
            self.status_updated.emit(f"Đang tải về {file_name}...")
            
            # Tải file với progress
            response = requests.get(download_url, stream=True, timeout=30)
            response.raise_for_status()
            
            downloaded_size = 0
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        if file_size > 0:
                            progress = int((downloaded_size / file_size) * 100)
                            self.progress_updated.emit(progress)
            
            # Kiểm tra tính toàn vẹn file
            if file_size > 0 and os.path.getsize(download_path) != file_size:
                self.error_occurred.emit("File tải về bị hỏng")
                return None
            
            self.status_updated.emit("Tải về hoàn tất")
            self.update_downloaded.emit(download_path)
            return download_path
            
        except Exception as e:
            error_msg = f"Lỗi khi tải về: {str(e)}"
            self.error_occurred.emit(error_msg)
            return None
    
    def create_backup(self) -> bool:
        """Tạo backup ứng dụng hiện tại"""
        try:
            self.status_updated.emit("Đang tạo backup...")
            
            # Tạo tên backup với timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"backup_{timestamp}"
            backup_path = os.path.join(self.backup_dir, backup_name)
            
            # Tạo thư mục backup
            os.makedirs(backup_path, exist_ok=True)
            
            # Copy executable hiện tại
            current_exe = sys.argv[0]
            if os.path.exists(current_exe):
                shutil.copy2(current_exe, backup_path)
            
            # Copy các file quan trọng
            important_files = ['version.json', 'config.json', 'key_cache.json']
            for file in important_files:
                file_path = os.path.join(self.app_dir, file)
                if os.path.exists(file_path):
                    shutil.copy2(file_path, backup_path)
            
            # Lưu thông tin backup
            backup_info = {
                "timestamp": timestamp,
                "version": self.current_version,
                "path": backup_path,
                "created": datetime.now().isoformat()
            }
            
            backup_info_file = os.path.join(backup_path, "backup_info.json")
            with open(backup_info_file, 'w', encoding='utf-8') as f:
                json.dump(backup_info, f, indent=2, ensure_ascii=False)
            
            self.status_updated.emit("Backup hoàn tất")
            return True
            
        except Exception as e:
            error_msg = f"Lỗi khi tạo backup: {str(e)}"
            self.error_occurred.emit(error_msg)
            return False
    
    def install_update(self, update_file: str) -> bool:
        """Cài đặt update"""
        try:
            self.status_updated.emit("Đang cài đặt cập nhật...")
            
            # Tạo backup trước khi update
            if not self.create_backup():
                return False
            
            current_exe = sys.argv[0]
            
            if update_file.endswith('.exe'):
                # Update trực tiếp file EXE
                temp_exe = current_exe + '.new'
                shutil.copy2(update_file, temp_exe)
                
                # Tạo script để thay thế file cũ
                self.create_update_script(temp_exe, current_exe)
                
            elif update_file.endswith('.zip'):
                # Giải nén và update
                with zipfile.ZipFile(update_file, 'r') as zip_ref:
                    extract_path = os.path.join(self.cache_dir, "update_extract")
                    zip_ref.extractall(extract_path)
                    
                    # Tìm file EXE trong archive
                    exe_file = None
                    for root, dirs, files in os.walk(extract_path):
                        for file in files:
                            if file.endswith('.exe'):
                                exe_file = os.path.join(root, file)
                                break
                        if exe_file:
                            break
                    
                    if not exe_file:
                        self.error_occurred.emit("Không tìm thấy file EXE trong update")
                        return False
                    
                    # Copy file mới
                    temp_exe = current_exe + '.new'
                    shutil.copy2(exe_file, temp_exe)
                    
                    # Tạo script update
                    self.create_update_script(temp_exe, current_exe)
            
            self.status_updated.emit("Cài đặt hoàn tất. Ứng dụng sẽ khởi động lại.")
            return True
            
        except Exception as e:
            error_msg = f"Lỗi khi cài đặt: {str(e)}"
            self.error_occurred.emit(error_msg)
            return False
    
    def create_update_script(self, new_exe: str, current_exe: str):
        """Tạo script để thay thế file EXE và khởi động lại"""
        script_path = os.path.join(self.cache_dir, "update_script.bat")
        
        script_content = f'''@echo off
timeout /t 2 /nobreak > nul
taskkill /f /im "{os.path.basename(current_exe)}" > nul 2>&1
timeout /t 1 /nobreak > nul
move /y "{new_exe}" "{current_exe}"
start "" "{current_exe}"
del "%~f0"
'''
        
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        # Chạy script và thoát ứng dụng
        subprocess.Popen(['cmd', '/c', script_path], 
                        creationflags=subprocess.CREATE_NO_WINDOW)
    
    def save_last_check(self, release_data: Dict[str, Any]):
        """Lưu thông tin kiểm tra update cuối cùng"""
        check_info = {
            "timestamp": datetime.now().isoformat(),
            "latest_version": release_data.get('tag_name', ''),
            "current_version": self.current_version,
            "release_url": release_data.get('html_url', ''),
            "release_name": release_data.get('name', ''),
            "release_body": release_data.get('body', '')
        }
        
        try:
            with open(self.last_check_file, 'w', encoding='utf-8') as f:
                json.dump(check_info, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    
    def get_last_check_info(self) -> Optional[Dict[str, Any]]:
        """Lấy thông tin kiểm tra update cuối cùng"""
        try:
            if os.path.exists(self.last_check_file):
                with open(self.last_check_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return None
    
    def cleanup_old_backups(self, keep_count: int = 5):
        """Dọn dẹp backup cũ, chỉ giữ lại số lượng nhất định"""
        try:
            if not os.path.exists(self.backup_dir):
                return
            
            backups = []
            for item in os.listdir(self.backup_dir):
                item_path = os.path.join(self.backup_dir, item)
                if os.path.isdir(item_path) and item.startswith('backup_'):
                    backups.append((item_path, os.path.getctime(item_path)))
            
            # Sắp xếp theo thời gian, giữ lại backup mới nhất
            backups.sort(key=lambda x: x[1], reverse=True)
            
            # Xóa backup cũ
            for backup_path, _ in backups[keep_count:]:
                shutil.rmtree(backup_path, ignore_errors=True)
                
        except Exception:
            pass


class UpdateManager(QObject):
    """Manager chính để quản lý update"""
    
    def __init__(self, repo_owner: str, repo_name: str, parent=None):
        super().__init__(parent)
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        
        # Đọc version hiện tại
        self.current_version = self.get_current_version()
        
        # Tạo checker
        self.checker = UpdateChecker(repo_owner, repo_name, self.current_version)
        
        # Connect signals
        self.checker.update_available.connect(self.on_update_available)
        self.checker.error_occurred.connect(self.on_error)
    
    def get_current_version(self) -> str:
        """Lấy version hiện tại từ version.json"""
        try:
            version_file = os.path.join(os.path.dirname(sys.argv[0]), 'version.json')
            if os.path.exists(version_file):
                with open(version_file, 'r', encoding='utf-8') as f:
                    version_data = json.load(f)
                    return version_data.get('version', '1.0.0')
        except Exception:
            pass
        return '1.0.0'
    
    def check_for_updates_async(self):
        """Kiểm tra update trong background thread"""
        def check_thread():
            self.checker.check_for_updates()
        
        thread = threading.Thread(target=check_thread, daemon=True)
        thread.start()
    
    def on_update_available(self, release_data: Dict[str, Any]):
        """Xử lý khi có update available"""
        latest_version = release_data.get('tag_name', 'Unknown')
        release_name = release_data.get('name', 'Update Available')
        release_notes = release_data.get('body', 'No release notes available')
        
        # Hiển thị dialog xác nhận
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Có phiên bản mới")
        msg.setText(f"Phiên bản mới {latest_version} đã có sẵn!")
        msg.setInformativeText(f"Phiên bản hiện tại: {self.current_version}\\n"
                              f"Phiên bản mới: {latest_version}\\n\\n"
                              f"Bạn có muốn cập nhật không?")
        msg.setDetailedText(f"Release Notes:\\n{release_notes}")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.Yes)
        
        if msg.exec_() == QMessageBox.Yes:
            self.download_and_install_update(release_data)
    
    def download_and_install_update(self, release_data: Dict[str, Any]):
        """Tải về và cài đặt update với progress dialog"""
        # Tạo progress dialog
        progress = QProgressDialog("Đang tải về cập nhật...", "Hủy", 0, 100)
        progress.setWindowTitle("Cập nhật ứng dụng")
        progress.setModal(True)
        progress.show()
        
        # Connect signals
        self.checker.progress_updated.connect(progress.setValue)
        self.checker.status_updated.connect(progress.setLabelText)
        
        def on_downloaded(file_path: str):
            progress.setLabelText("Đang cài đặt...")
            if self.checker.install_update(file_path):
                progress.close()
                # Ứng dụng sẽ tự khởi động lại
                QApplication.quit()
            else:
                progress.close()
        
        def on_error(error_msg: str):
            progress.close()
            QMessageBox.critical(None, "Lỗi cập nhật", error_msg)
        
        self.checker.update_downloaded.connect(on_downloaded)
        self.checker.error_occurred.connect(on_error)
        
        # Bắt đầu download trong thread riêng
        def download_thread():
            self.checker.download_update(release_data)
        
        thread = threading.Thread(target=download_thread, daemon=True)
        thread.start()
        
        # Xử lý cancel
        def on_canceled():
            thread.join(timeout=1)
            
        progress.canceled.connect(on_canceled)
    
    def on_error(self, error_msg: str):
        """Xử lý lỗi"""
        print(f"Update Error: {error_msg}")
    
    def force_check_update(self):
        """Ép buộc kiểm tra update (cho menu Help > Check for Updates)"""
        self.check_for_updates_async()


# Convenience function
def create_update_manager(repo_owner: str, repo_name: str, parent=None) -> UpdateManager:
    """Tạo UpdateManager instance"""
    return UpdateManager(repo_owner, repo_name, parent)


if __name__ == "__main__":
    # Test
    import sys
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Test với repo giả định
    manager = create_update_manager("your-username", "voice-app")
    manager.force_check_update()
    
    sys.exit(app.exec_())
