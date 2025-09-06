# VoiceUpdate - Voice Generation Application

🎤 Ứng dụng tổng hợp giọng nói Việt Nam với F5-TTS và tính năng tự động cập nhật.

## ✨ Tính năng

- 🎯 **Tổng hợp giọng nói tiếng Việt** với công nghệ F5-TTS
- 🔄 **Tự động cập nhật** ứng dụng từ GitHub Releases  
- 📦 **Đồng bộ models** từ Google Drive
- 🖥️ **Giao diện thân thiện** với PyQt5
- 🔐 **Bảo mật models** với mã hóa
- 🎛️ **Xử lý background** không blocking UI

## 📋 Yêu cầu

- Windows 10/11 (64-bit)
- Kết nối internet (để tải models và cập nhật)
- RAM: 8GB+ (khuyến nghị)
- Dung lượng: 2GB+ (cho models)

## 🚀 Cài đặt

### Phiên bản Portable (Khuyến nghị)

1. Tải file `VoiceApp_vX.X.X_Portable.zip` từ [Releases](https://github.com/nguyentruongduy1410/VoiceUpdate/releases)
2. Giải nén vào thư mục bất kỳ
3. Chạy `VoiceApp.exe`
4. Làm theo hướng dẫn setup

### Build từ Source

```bash
# Clone repository
git clone https://github.com/nguyentruongduy1410/VoiceUpdate.git
cd VoiceUpdate

# Cài đặt dependencies
pip install -r requirements.txt

# Build EXE
python build.py

# Hoặc chạy trực tiếp
python main.py
```

## 📱 Cách sử dụng

1. **Khởi động ứng dụng**: Chạy `VoiceApp.exe`
2. **Đăng nhập**: Nhập key license (liên hệ để nhận key)
3. **Chọn model**: Ứng dụng sẽ tự động tải models cần thiết
4. **Tổng hợp giọng**: Nhập text và tạo audio
5. **Cập nhật**: Ứng dụng tự động kiểm tra và cập nhật

## 🔧 Cấu hình

### Auto Update
- Kiểm tra cập nhật mỗi 6 giờ
- Tự động backup version cũ
- Có thể tắt trong settings

### Model Sync  
- Đồng bộ models từ Google Drive
- Kiểm tra version mới mỗi 24 giờ
- Backup models cũ trước khi cập nhật

## 🏗️ Development

### Build Requirements
```bash
pip install pyinstaller
pip install -r requirements.txt
```

### Build Commands
```bash
# Test update system
python test_update.py

# Build portable package
python build.py

# Build with installer
python build.py --skip-installer
```

### GitHub Actions
- Tự động build khi push tag
- Tạo GitHub Release
- Upload portable package

## 📂 Cấu trúc Project

```
VoiceUpdate/
├── main.py                 # Entry point
├── build.py               # Build script
├── build.spec             # PyInstaller config
├── requirements.txt       # Dependencies
├── version.json           # Version info
├── update_manager.py      # Update system
├── model_sync.py         # Model sync
├── auto_updater.py       # Auto updater
├── ui/                   # UI components
├── f5_tts/              # F5-TTS integration
├── models/              # Model files
├── secure_models/       # Encrypted models
└── .github/             # GitHub Actions
```

## 🔐 Security

- Models được mã hóa trong `secure_models/`
- Key authentication cho truy cập
- HTTPS cho tất cả downloads
- Verify checksums khi cập nhật

## 📞 Hỗ trợ

- **Developer**: Thầy Lưu Hà
- **Phone**: 0931681969
- **Issues**: [GitHub Issues](https://github.com/nguyentruongduy1410/VoiceUpdate/issues)

## 📄 License

© 2025 Thầy Lưu Hà. All rights reserved.

## 🆕 Changelog

### v1.0.1 (Latest)
- ✅ Auto update system
- ✅ Model sync from Google Drive  
- ✅ Improved UI
- ✅ Bug fixes

### v1.0.0
- 🎉 Initial release
- ✅ Basic voice synthesis
- ✅ Vietnamese support
