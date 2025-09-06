"""
Auto Updater - Tự động kiểm tra và cập nhật khi khởi động

Chức năng:
- Kiểm tra update khi khởi động ứng dụng
- Tự động tải về và cài đặt update trong background
- Đồng bộ models từ Google Drive
- Thông báo người dùng về các cập nhật
"""

import os
import sys
import json
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from PyQt5.QtWidgets import QMessageBox, QSystemTrayIcon, QMenu, QAction, QApplication

# Import local modules
from update_manager import UpdateManager
from model_sync import ModelSyncManager


class AutoUpdater(QObject):
    """Auto updater chính"""
    
    # Signals
    update_check_started = pyqtSignal()
    update_check_completed = pyqtSignal(bool)  # True nếu có update
    model_sync_started = pyqtSignal()
    model_sync_completed = pyqtSignal(bool)    # True nếu có update
    notification_requested = pyqtSignal(str, str)  # title, message
    
    def __init__(self, repo_owner: str, repo_name: str, parent=None):
        super().__init__(parent)
        
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        
        # Managers
        self.update_manager = None
        self.model_sync_manager = None
        
        # Timers
        self.update_timer = QTimer()
        self.model_timer = QTimer()
        
        # Settings
        self.settings_file = os.path.join(
            os.path.dirname(sys.argv[0]), 
            ".cache", 
            "auto_updater_settings.json"
        )
        self.settings = self.load_settings()
        
        # Setup timers
        self.setup_timers()
        
        # Initialize managers
        self.init_managers()
    
    def load_settings(self) -> Dict[str, Any]:
        """Tải cài đặt auto updater"""
        default_settings = {
            "auto_check_updates": True,
            "auto_check_models": True,
            "update_check_interval_hours": 6,
            "model_check_interval_hours": 24,
            "silent_update": False,
            "auto_install_updates": False,
            "auto_install_models": True,
            "last_update_check": None,
            "last_model_check": None,
            "startup_delay_seconds": 30
        }
        
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    return {**default_settings, **settings}
        except Exception:
            pass
        
        # Tạo file settings mặc định
        os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
        self.save_settings(default_settings)
        return default_settings
    
    def save_settings(self, settings: Dict[str, Any] = None):
        """Lưu cài đặt"""
        if settings is None:
            settings = self.settings
        
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Lỗi lưu settings: {e}")
    
    def init_managers(self):
        """Khởi tạo các managers"""
        try:
            # Update manager
            self.update_manager = UpdateManager(self.repo_owner, self.repo_name, self)
            
            # Model sync manager
            self.model_sync_manager = ModelSyncManager()
            
            # Connect signals
            self.connect_manager_signals()
            
        except Exception as e:
            print(f"Lỗi khởi tạo managers: {e}")
    
    def connect_manager_signals(self):
        """Kết nối signals từ các managers"""
        if self.update_manager:
            self.update_manager.checker.update_available.connect(self.on_app_update_available)
            self.update_manager.checker.error_occurred.connect(self.on_update_error)
        
        if self.model_sync_manager:
            self.model_sync_manager.sync_completed.connect(self.on_model_sync_completed)
            self.model_sync_manager.sync_error.connect(self.on_model_sync_error)
            self.model_sync_manager.model_updated.connect(self.on_model_updated)
    
    def setup_timers(self):
        """Thiết lập timers"""
        # Timer cho update check
        self.update_timer.timeout.connect(self.check_for_app_updates)
        self.update_timer.setSingleShot(False)
        
        # Timer cho model sync
        self.model_timer.timeout.connect(self.check_for_model_updates)
        self.model_timer.setSingleShot(False)
    
    def start_auto_updater(self):
        """Bắt đầu auto updater"""
        if not self.settings.get("auto_check_updates", True) and not self.settings.get("auto_check_models", True):
            return
        
        # Delay để không ảnh hưởng đến startup
        startup_delay = self.settings.get("startup_delay_seconds", 30) * 1000
        QTimer.singleShot(startup_delay, self.perform_startup_checks)
        
        # Bắt đầu periodic checks
        self.start_periodic_checks()
    
    def start_periodic_checks(self):
        """Bắt đầu kiểm tra định kỳ"""
        if self.settings.get("auto_check_updates", True):
            interval_hours = self.settings.get("update_check_interval_hours", 6)
            self.update_timer.start(interval_hours * 60 * 60 * 1000)  # Convert to ms
        
        if self.settings.get("auto_check_models", True):
            interval_hours = self.settings.get("model_check_interval_hours", 24)
            self.model_timer.start(interval_hours * 60 * 60 * 1000)  # Convert to ms
    
    def stop_auto_updater(self):
        """Dừng auto updater"""
        self.update_timer.stop()
        self.model_timer.stop()
    
    def perform_startup_checks(self):
        """Thực hiện kiểm tra khi startup"""
        # Kiểm tra xem có cần check không
        if self.should_check_updates():
            self.check_for_app_updates()
        
        if self.should_check_models():
            self.check_for_model_updates()
    
    def should_check_updates(self) -> bool:
        """Kiểm tra có nên check app updates không"""
        if not self.settings.get("auto_check_updates", True):
            return False
        
        last_check = self.settings.get("last_update_check")
        if not last_check:
            return True
        
        try:
            last_check_time = datetime.fromisoformat(last_check)
            interval_hours = self.settings.get("update_check_interval_hours", 6)
            
            return datetime.now() - last_check_time >= timedelta(hours=interval_hours)
        except Exception:
            return True
    
    def should_check_models(self) -> bool:
        """Kiểm tra có nên check model updates không"""
        if not self.settings.get("auto_check_models", True):
            return False
        
        last_check = self.settings.get("last_model_check")
        if not last_check:
            return True
        
        try:
            last_check_time = datetime.fromisoformat(last_check)
            interval_hours = self.settings.get("model_check_interval_hours", 24)
            
            return datetime.now() - last_check_time >= timedelta(hours=interval_hours)
        except Exception:
            return True
    
    def check_for_app_updates(self):
        """Kiểm tra app updates"""
        if not self.update_manager:
            return
        
        self.update_check_started.emit()
        
        def check_thread():
            try:
                # Cập nhật thời gian check cuối cùng
                self.settings["last_update_check"] = datetime.now().isoformat()
                self.save_settings()
                
                # Thực hiện check
                has_update = self.update_manager.checker.check_for_updates()
                self.update_check_completed.emit(has_update)
                
            except Exception as e:
                print(f"Lỗi check app updates: {e}")
                self.update_check_completed.emit(False)
        
        thread = threading.Thread(target=check_thread, daemon=True)
        thread.start()
    
    def check_for_model_updates(self):
        """Kiểm tra model updates"""
        if not self.model_sync_manager:
            return
        
        self.model_sync_started.emit()
        
        def check_thread():
            try:
                # Cập nhật thời gian check cuối cùng
                self.settings["last_model_check"] = datetime.now().isoformat()
                self.save_settings()
                
                # Kiểm tra models cần update
                models_to_update = self.model_sync_manager.check_for_model_updates()
                
                if models_to_update:
                    if self.settings.get("auto_install_models", True):
                        # Tự động sync models
                        self.model_sync_manager.sync_models_async(models_to_update)
                    else:
                        # Thông báo có models cần update
                        self.notification_requested.emit(
                            "Model Updates Available",
                            f"Có {len(models_to_update)} model(s) cần cập nhật: {', '.join(models_to_update)}"
                        )
                    
                    self.model_sync_completed.emit(True)
                else:
                    self.model_sync_completed.emit(False)
                
            except Exception as e:
                print(f"Lỗi check model updates: {e}")
                self.model_sync_completed.emit(False)
        
        thread = threading.Thread(target=check_thread, daemon=True)
        thread.start()
    
    def on_app_update_available(self, release_data: Dict[str, Any]):
        """Xử lý khi có app update"""
        latest_version = release_data.get('tag_name', 'Unknown')
        
        if self.settings.get("silent_update", False):
            # Silent mode - chỉ thông báo nhỏ
            self.notification_requested.emit(
                "Update Available",
                f"Phiên bản {latest_version} đã có sẵn. Kiểm tra menu Help > Check for Updates."
            )
        elif self.settings.get("auto_install_updates", False):
            # Tự động cài đặt
            self.notification_requested.emit(
                "Auto Update",
                f"Đang tự động cập nhật lên phiên bản {latest_version}..."
            )
            self.update_manager.download_and_install_update(release_data)
        else:
            # Hiển thị dialog như bình thường (được xử lý bởi UpdateManager)
            pass
    
    def on_update_error(self, error_msg: str):
        """Xử lý lỗi update"""
        if not self.settings.get("silent_update", False):
            self.notification_requested.emit("Update Error", error_msg)
    
    def on_model_sync_completed(self):
        """Xử lý khi model sync hoàn thành"""
        pass
    
    def on_model_sync_error(self, error_msg: str):
        """Xử lý lỗi model sync"""
        if not self.settings.get("silent_update", False):
            self.notification_requested.emit("Model Sync Error", error_msg)
    
    def on_model_updated(self, model_name: str):
        """Xử lý khi có model được update"""
        self.notification_requested.emit(
            "Model Updated",
            f"Model '{model_name}' đã được cập nhật thành công."
        )
    
    def force_check_all(self):
        """Ép buộc kiểm tra tất cả updates"""
        self.check_for_app_updates()
        self.check_for_model_updates()
    
    def toggle_auto_updates(self, enabled: bool):
        """Bật/tắt auto updates"""
        self.settings["auto_check_updates"] = enabled
        self.save_settings()
        
        if enabled:
            self.start_periodic_checks()
        else:
            self.update_timer.stop()
    
    def toggle_auto_models(self, enabled: bool):
        """Bật/tắt auto model sync"""
        self.settings["auto_check_models"] = enabled
        self.save_settings()
        
        if enabled:
            self.start_periodic_checks()
        else:
            self.model_timer.stop()
    
    def set_update_interval(self, hours: int):
        """Thiết lập interval cho update check"""
        self.settings["update_check_interval_hours"] = hours
        self.save_settings()
        
        if self.settings.get("auto_check_updates", True):
            self.update_timer.stop()
            self.update_timer.start(hours * 60 * 60 * 1000)
    
    def set_model_interval(self, hours: int):
        """Thiết lập interval cho model check"""
        self.settings["model_check_interval_hours"] = hours
        self.save_settings()
        
        if self.settings.get("auto_check_models", True):
            self.model_timer.stop()
            self.model_timer.start(hours * 60 * 60 * 1000)
    
    def get_status_info(self) -> Dict[str, Any]:
        """Lấy thông tin trạng thái"""
        return {
            "auto_updates_enabled": self.settings.get("auto_check_updates", True),
            "auto_models_enabled": self.settings.get("auto_check_models", True),
            "last_update_check": self.settings.get("last_update_check"),
            "last_model_check": self.settings.get("last_model_check"),
            "update_interval_hours": self.settings.get("update_check_interval_hours", 6),
            "model_interval_hours": self.settings.get("model_check_interval_hours", 24),
            "silent_mode": self.settings.get("silent_update", False)
        }


class NotificationHandler(QObject):
    """Xử lý thông báo cho auto updater"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tray_icon = None
        self.init_tray_icon()
    
    def init_tray_icon(self):
        """Khởi tạo system tray icon"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        
        try:
            app = QApplication.instance()
            if app:
                self.tray_icon = QSystemTrayIcon(self)
                
                # Thiết lập icon
                icon_path = os.path.join(os.path.dirname(sys.argv[0]), "icon.ico")
                if os.path.exists(icon_path):
                    from PyQt5.QtGui import QIcon
                    self.tray_icon.setIcon(QIcon(icon_path))
                else:
                    self.tray_icon.setIcon(app.style().standardIcon(app.style().SP_ComputerIcon))
                
                # Thiết lập menu
                self.setup_tray_menu()
                
                self.tray_icon.show()
        except Exception as e:
            print(f"Lỗi khởi tạo tray icon: {e}")
    
    def setup_tray_menu(self):
        """Thiết lập menu cho tray icon"""
        if not self.tray_icon:
            return
        
        menu = QMenu()
        
        # Check for updates action
        check_action = QAction("Check for Updates", self)
        check_action.triggered.connect(self.request_force_check)
        menu.addAction(check_action)
        
        menu.addSeparator()
        
        # Show main window action
        show_action = QAction("Show App", self)
        show_action.triggered.connect(self.request_show_app)
        menu.addAction(show_action)
        
        # Quit action
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(menu)
    
    def show_notification(self, title: str, message: str):
        """Hiển thị notification"""
        if self.tray_icon and self.tray_icon.supportsMessages():
            self.tray_icon.showMessage(title, message, QSystemTrayIcon.Information, 5000)
        else:
            # Fallback: hiển thị message box
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Information)
            msg.setWindowTitle(title)
            msg.setText(message)
            msg.exec_()
    
    def request_force_check(self):
        """Signal để request force check"""
        # Emit signal or call parent method
        pass
    
    def request_show_app(self):
        """Signal để hiển thị app"""
        # Emit signal or call parent method
        pass


def create_auto_updater(repo_owner: str, repo_name: str, parent=None) -> AutoUpdater:
    """Tạo AutoUpdater instance"""
    return AutoUpdater(repo_owner, repo_name, parent)


if __name__ == "__main__":
    # Test
    import sys
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Test với repo giả định
    updater = create_auto_updater("your-username", "voice-app")
    updater.start_auto_updater()
    
    # Tạo notification handler
    notif_handler = NotificationHandler()
    updater.notification_requested.connect(notif_handler.show_notification)
    
    print("Auto updater started. Check console for activity.")
    
    sys.exit(app.exec_())
