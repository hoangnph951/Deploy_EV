# Đăng ký, đăng nhập và “Xe của tôi”

## Luồng sử dụng

1. Người dùng đăng ký bằng họ tên, email, số điện thoại tùy chọn và mật khẩu.
2. Backend tạo tài khoản, băm mật khẩu bằng PBKDF2-SHA256 và trả opaque access token.
3. Sau đăng ký lần đầu, frontend chuyển sang bước **Xe của tôi**.
4. Người dùng chọn mẫu xe trong danh mục profile đã xác minh. Biển số và tên gợi nhớ là tùy chọn.
5. Xe mặc định quyết định `vehicle_profile_id` được gửi vào planner.

Người dùng không được tự sửa dung lượng pin, connector, công suất sạc hoặc baseline tiêu hao. Đây là các thông số ảnh hưởng trực tiếp tới an toàn và phải đến từ profile được version hóa.

## API

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `GET /api/v1/vehicle-profiles`
- `GET /api/v1/me/vehicles`
- `POST /api/v1/me/vehicles`
- `PATCH /api/v1/me/vehicles/{vehicle_id}/default`

Các API `/trips` yêu cầu `Authorization: Bearer <access_token>` trong development và production. Header `X-User-Id` chỉ được chấp nhận khi `APP_ENV=test` để giữ fixture test deterministic.

## Cơ sở dữ liệu

Migration `20260815_0010` tạo ba bảng:

- `users`: hồ sơ tài khoản và password hash;
- `auth_sessions`: hash của access token, hạn dùng và thời điểm thu hồi;
- `user_vehicles`: xe thuộc người dùng và liên kết tới `vehicle_profiles`.

Migration `20260815_0130` bổ sung catalog 8 profile VinFast có version riêng:

- VF 3;
- VF 5 Plus;
- VF 6 Eco;
- VF 6 Plus;
- VF 7 Eco 2024;
- VF 7 Plus AWD 2024;
- VF 8 Eco CATL;
- VF 8 Plus CATL.

Mỗi profile lưu riêng dung lượng pin khả dụng, range kèm chuẩn NEDC/WLTP, công suất sạc DC tối đa, động cơ, mô-men xoắn, khối lượng và nguồn VinFast chính hãng. Baseline Wh/km là giá trị dẫn xuất minh bạch từ dung lượng pin chia cho range kiểm định của đúng phiên bản; đây không phải số đo tiêu hao realtime. VF 9 chưa được đưa vào planner vì nguồn FAQ chính hãng hiện vẫn ghi công suất sạc nhanh DC là “cập nhật thông tin sau”.

Chạy local:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

Docker/Render tự chạy `alembic upgrade head` trước khi khởi động FastAPI.

Google/Microsoft OAuth chưa được cấu hình. Hai lựa chọn trên UI được vô hiệu hóa và ghi rõ, không giả lập đăng nhập mạng xã hội.
