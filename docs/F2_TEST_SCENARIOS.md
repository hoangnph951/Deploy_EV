# 10 tình huống kiểm tra tính năng F2

## Mục tiêu

F2 giúp người dùng làm được ba việc chính:

1. Hiểu vì sao hệ thống đề xuất một kế hoạch chuyến đi.
2. Tự quyết định xác nhận hoặc từ chối kế hoạch đó.
3. Xem lại các kế hoạch cũ mà không bị mất dữ liệu.

Dưới đây là 10 tình huống thực tế dùng để kiểm tra F2. Tài liệu được viết theo góc nhìn người sử dụng để người không làm kỹ thuật vẫn có thể đọc, thao tác và đánh giá kết quả.

---

## Tình huống 1: Kế hoạch mới không được tự động áp dụng

**Bối cảnh**

Người dùng nhập hành trình từ Hà Nội đến Vinh và yêu cầu hệ thống lập kế hoạch.

**Thao tác kiểm tra**

1. Tạo một chuyến đi mới với mức pin ban đầu là 90%.
2. Yêu cầu hệ thống đề xuất kế hoạch.
3. Chưa bấm nút xác nhận.

**Kết quả mong đợi**

- Kế hoạch được hiển thị để người dùng xem trước.
- Hệ thống không tự động áp dụng kế hoạch.
- Chuyến đi chỉ bắt đầu sau khi chính người dùng bấm xác nhận.

**Ý nghĩa**

Hệ thống chỉ đóng vai trò tư vấn. Quyền quyết định cuối cùng luôn thuộc về người lái xe.

**Kết quả hiện tại:** Đạt.

---

## Tình huống 2: Hệ thống phải giải thích được vì sao chọn kế hoạch này

**Bối cảnh**

Hệ thống đã tìm được một hoặc nhiều phương án cho chuyến đi.

**Thao tác kiểm tra**

1. Mở kế hoạch được đề xuất.
2. Đọc phần giải thích lý do lựa chọn.
3. So sánh lời giải thích với thông tin đang hiển thị như thời gian đi, điểm sạc, quãng đường vòng và mức pin dự kiến.

**Kết quả mong đợi**

- Hệ thống đưa ra lý do rõ ràng, dễ hiểu.
- Lời giải thích phù hợp với kế hoạch thực tế.
- Hệ thống không nhắc đến trạm sạc hoặc con số không xuất hiện trong kết quả.
- Nếu dịch vụ AI gặp lỗi, người dùng vẫn nhận được lời giải thích cơ bản thay vì một vùng nội dung trống.

**Ý nghĩa**

Người dùng cần biết hệ thống dựa vào đâu để đưa ra đề xuất, thay vì phải tin vào một kết quả không có căn cứ.

**Kết quả hiện tại:** Đạt ở mức giải thích cơ bản.

---

## Tình huống 3: Chuyến đi không an toàn không được đưa ra để xác nhận

**Bối cảnh**

Xe chỉ còn 10% pin, thấp hơn mức pin an toàn 15% mà hệ thống đang áp dụng.

**Thao tác kiểm tra**

1. Tạo chuyến đi với mức pin ban đầu là 10%.
2. Yêu cầu hệ thống lập kế hoạch.
3. Kiểm tra kết quả và danh sách các kế hoạch đã tạo.

**Kết quả mong đợi**

- Hệ thống thông báo rằng chưa tìm được kế hoạch an toàn.
- Người dùng không nhìn thấy nút xác nhận cho một kế hoạch không an toàn.
- Kế hoạch lỗi không xuất hiện trong lịch sử như một phương án hợp lệ.
- Hệ thống giải thích được nguyên nhân liên quan đến mức pin quá thấp.

**Ý nghĩa**

Một phương án không bảo đảm an toàn không được phép đi tiếp vào bước xác nhận, dù các phần còn lại của phép tính có thể đã hoàn thành.

**Kết quả hiện tại:** Đạt.

---

## Tình huống 4: Người khác không được xem kế hoạch chuyến đi

**Bối cảnh**

Người dùng A đã tạo một chuyến đi và có kế hoạch riêng. Người dùng B biết mã của chuyến đi đó và thử truy cập.

**Thao tác kiểm tra**

1. Đăng nhập bằng tài khoản A và tạo kế hoạch.
2. Chuyển sang tài khoản B.
3. Thử mở lịch sử kế hoạch của A.

**Kết quả mong đợi**

- Người dùng B bị từ chối truy cập.
- Không có thông tin nào về tuyến đường, trạm sạc hoặc mức pin của A bị hiển thị.
- Kế hoạch của A vẫn giữ nguyên.

**Ý nghĩa**

Thông tin hành trình và vị trí xe là dữ liệu cá nhân. Biết mã chuyến đi không đồng nghĩa với việc được phép xem chuyến đi đó.

**Kết quả hiện tại:** Đạt.

---

## Tình huống 5: Tạo kế hoạch mới không làm mất kế hoạch cũ

**Bối cảnh**

Người dùng đã có một kế hoạch, sau đó yêu cầu hệ thống tính lại để có phương án mới.

**Thao tác kiểm tra**

1. Tạo kế hoạch lần đầu.
2. Ghi nhận thông tin tuyến đường, trạm sạc và mức pin dự kiến.
3. Yêu cầu hệ thống tạo kế hoạch lần thứ hai.
4. Mở lịch sử kế hoạch.

**Kết quả mong đợi**

- Cả kế hoạch lần đầu và lần thứ hai đều còn trong lịch sử.
- Nội dung của kế hoạch đầu tiên không bị thay đổi.
- Hai kế hoạch được phân biệt rõ ràng theo thứ tự tạo.
- Người dùng có thể mở lại từng kế hoạch để xem.

**Ý nghĩa**

Lịch sử phải phản ánh đúng những gì từng xảy ra. Nếu kế hoạch cũ bị ghi đè, người dùng sẽ không thể so sánh hoặc kiểm tra lại quyết định trước đó.

**Kết quả hiện tại:** Đạt.

---

## Tình huống 6: Chủ xe xác nhận một kế hoạch phù hợp

**Bối cảnh**

Người dùng đã đọc tuyến đường, các điểm sạc, mức pin dự kiến và đồng ý với đề xuất.

**Thao tác kiểm tra**

1. Mở một kế hoạch đang chờ quyết định.
2. Bấm **Xác nhận kế hoạch**.
3. Mở lại chuyến đi và lịch sử kế hoạch.

**Kết quả mong đợi**

- Hệ thống thông báo xác nhận thành công.
- Kế hoạch được đánh dấu là đã xác nhận.
- Chuyến đi chuyển sang trạng thái sẵn sàng hoạt động.
- Khi tải lại trang, kết quả xác nhận vẫn được giữ nguyên.

**Ý nghĩa**

Đây là luồng sử dụng chính của F2: xem đề xuất, hiểu đề xuất và chủ động đồng ý.

**Kết quả hiện tại:** Chưa hoàn thiện.

---

## Tình huống 7: Người dùng từ chối một kế hoạch không phù hợp

**Bối cảnh**

Người dùng thấy kế hoạch đi đường vòng quá xa hoặc có điểm sạc không thuận tiện.

**Thao tác kiểm tra**

1. Mở kế hoạch đang chờ quyết định.
2. Bấm **Từ chối**.
3. Nhập lý do: “Đường vòng quá xa”.
4. Mở lại lịch sử kế hoạch.

**Kết quả mong đợi**

- Kế hoạch được đánh dấu là đã từ chối.
- Lý do từ chối được lưu lại.
- Chuyến đi không tự động bắt đầu.
- Kế hoạch không bị xoá khỏi lịch sử.
- Nếu trước đó đã có một kế hoạch đang được sử dụng, kế hoạch cũ vẫn tiếp tục có hiệu lực.

**Ý nghĩa**

Từ chối không có nghĩa là xoá dấu vết. Hệ thống cần lưu lại quyết định để sau này người dùng có thể kiểm tra vì sao phương án đó không được chọn.

**Kết quả hiện tại:** Chưa hoàn thiện.

---

## Tình huống 8: Người khác không được xác nhận thay chủ xe

**Bối cảnh**

Người dùng A tạo chuyến đi. Người dùng B tìm cách xác nhận kế hoạch của A.

**Thao tác kiểm tra**

1. Tài khoản A tạo một kế hoạch mới.
2. Tài khoản B thử bấm xác nhận kế hoạch đó.
3. Tài khoản A mở lại kế hoạch để kiểm tra.

**Kết quả mong đợi**

- Hệ thống từ chối thao tác của B.
- Kế hoạch vẫn ở trạng thái chờ A quyết định.
- Chuyến đi không bị bắt đầu ngoài ý muốn.
- A vẫn có thể tự xác nhận hoặc từ chối sau đó.

**Ý nghĩa**

Không ai được phép quyết định thay chủ xe, kể cả khi họ biết mã của kế hoạch.

**Kết quả hiện tại:** Chưa hoàn thiện.

---

## Tình huống 9: Không được xác nhận một kế hoạch đã cũ

**Bối cảnh**

Người dùng mở cùng một chuyến đi ở hai cửa sổ. Một cửa sổ đang hiển thị thông tin mới, cửa sổ còn lại vẫn giữ kế hoạch cũ.

**Thao tác kiểm tra**

1. Mở một kế hoạch ở hai cửa sổ khác nhau.
2. Ở cửa sổ thứ nhất, tạo hoặc tải kế hoạch mới hơn.
3. Quay lại cửa sổ thứ hai và thử xác nhận thông tin cũ.

**Kết quả mong đợi**

- Hệ thống không áp dụng kế hoạch cũ.
- Người dùng nhận được thông báo rằng dữ liệu đã thay đổi.
- Hệ thống yêu cầu tải lại kế hoạch mới nhất.
- Không có kế hoạch nào bị thay đổi do thao tác trên màn hình cũ.

**Ý nghĩa**

Tình huống này thường xảy ra khi người dùng mở nhiều cửa sổ hoặc để trang quá lâu. Hệ thống phải ngăn quyết định cũ ghi đè lên thông tin mới.

**Kết quả hiện tại:** Chưa hoàn thiện.

---

## Tình huống 10: Bấm xác nhận hai lần liên tiếp

**Bối cảnh**

Do mạng chậm hoặc chưa thấy phản hồi, người dùng bấm nút xác nhận hai lần rất nhanh.

**Thao tác kiểm tra**

1. Mở một kế hoạch đang chờ xác nhận.
2. Bấm nút xác nhận hai lần liên tiếp.
3. Kiểm tra trạng thái chuyến đi và lịch sử thao tác.

**Kết quả mong đợi**

- Chỉ một lần xác nhận được ghi nhận.
- Không tạo ra hai kế hoạch đã xác nhận giống nhau.
- Không xuất hiện dữ liệu trùng lặp.
- Người dùng nhận được kết quả rõ ràng thay vì màn hình treo hoặc báo thành công hai lần.

**Ý nghĩa**

Đây là tình huống rất dễ gặp trong thực tế. Hệ thống cần hoạt động đúng ngay cả khi người dùng bấm nhanh hoặc đường truyền phản hồi chậm.

**Kết quả hiện tại:** Chưa hoàn thiện.

---

## Tổng kết kết quả hiện tại

| Nhóm | Kết quả |
|---|---|
| Tình huống 1 đến 5 | Đã kiểm tra và đạt |
| Tình huống 6 đến 10 | Đã xác định kết quả mong đợi, phần chức năng tương ứng chưa hoàn thiện |

F2 chỉ nên được xem là hoàn thành khi cả 10 tình huống đều đạt.

Luồng demo cuối cùng cần thực hiện được trọn vẹn:

```text
Tạo kế hoạch
→ xem lý do đề xuất
→ xác nhận hoặc từ chối
→ tải lại vẫn giữ đúng kết quả
→ xem lại kế hoạch trong lịch sử
```

## Ghi chú cho nhóm phát triển

Các tình huống trên đã được chuyển thành test tự động trong `tests/test_api/test_f2.py`. Phần này chỉ phục vụ nhóm phát triển; người review tính năng có thể đánh giá hoàn toàn dựa trên 10 tình huống được mô tả ở trên.
