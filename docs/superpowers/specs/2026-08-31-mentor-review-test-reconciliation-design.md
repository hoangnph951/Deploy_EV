# Thiết Kế Đồng Bộ Các Test Trong Review Của Mentor

**Ngày:** 2026-08-31
**Trạng thái:** Đã được duyệt trong trao đổi; đang triển khai
**Review liên quan:** `mentor_feedback/review.md`
**Giữ nguyên thiết kế:** `docs/superpowers/specs/2026-08-28-f1-f4-closed-loop-integration-design.md`

## Mục Tiêu

Hoàn tất những thiếu sót trong review của mentor vẫn còn tồn tại trên nhánh hiện tại, khôi phục sự đồng bộ giữa test backend và implementation dùng trong thực tế, đồng thời giữ nguyên các thuật toán lập kế hoạch và agent F1/F4 đã ổn định.

## Bằng Chứng Hiện Tại

- Review của mentor được lập trước các commit tích hợp F4 mới nhất.
- Frontend hiện đã có khôi phục plan đang chờ từ máy chủ, điều khiển xác nhận/từ chối, xử lý phiên bản cũ, timeout/hủy luồng lập kế hoạch, các case mô phỏng cố định và các điều khiển tạm dừng/chạy tiếp/đặt lại/chạy từng bước.
- Kiểm tra frontend hiện đang pass: 18 test và bản build production.
- Full backend suite hiện có các lỗi legacy thuộc station graph/catalog ngoài phạm vi yêu cầu này. Các module F2/planning/persistence liên quan trực tiếp tới review vẫn có lỗi contract và vòng đời cần sửa.
- Một số contract persistence được test mong đợi từng tồn tại trong các commit `57e8a70` và `648404f`. Chúng chỉ được dùng làm tham chiếu cho F2/persistence, không dùng để khôi phục station graph.

## Ràng Buộc Bắt Buộc

- Không sửa graph agent F1/F4, hành vi supervisor, thứ tự planning node, thuật toán chọn trạm, công thức năng lượng, công thức feasibility, ngưỡng an toàn hoặc policy quyết định replanning.
- Giữ nguyên implementation vòng đời F4 hiện tại và ranh giới xác nhận plan đang chờ.
- Không cherry-pick hoặc khôi phục nguyên khối các commit lịch sử vì chúng chứa nhiều thay đổi không liên quan và mã F4 cũ hơn.
- Chỉ khôi phục contract, hành vi persistence, hạ tầng provider, migration và hành vi trình bày/API mà các test hiện tại cùng case mentor yêu cầu.
- Không làm yếu, xóa hoặc viết lại test chỉ để bộ test chuyển sang màu xanh.
- Không khôi phục station graph, station catalog ingestion, cache routing, worker graph hoặc migration của station graph.

## Phương Án Được Chọn

Dùng các test hiện tại làm contract hành vi và chỉ dùng các commit lịch sử làm implementation tham chiếu. Khôi phục hạ tầng bị thiếu theo các nhóm nhỏ có thứ tự dependency, đồng thời giữ API công khai trên nhánh hiện tại ở những nơi phiên bản hiện tại mới hơn.

Công việc được chia thành ba phạm vi:

1. Khôi phục persistence của trip/plan và hành vi trạng thái vòng đời mà F2 cùng luồng lịch sử/tải lại cần.
2. Khôi phục phân loại lỗi provider và metadata phản hồi mà không thay đổi quyết định lập kế hoạch.
3. Chạy hồi quy các module liên quan trực tiếp tới review và frontend hiện tại.

## Phạm Vi Được Phép Thay Đổi

Các file production dự kiến gồm:

- `src/packages/contracts/trips.py`
- `src/packages/core/trips/domain/entities.py`
- `src/packages/core/trips/infrastructure/models.py`
- `src/packages/core/trips/infrastructure/sqlalchemy_repository.py`
- `src/packages/core/trips/application/service.py`
- `src/apps/api/routes/trips.py` nếu cần đồng bộ mã HTTP của response đã có
- `migrations/versions/20260831_1400_restore_f2_plan_persistence.py`

Danh sách này có thể được thu hẹp trong quá trình triển khai. Chỉ thêm file mới khi một test hoặc dependency migration hiện có thực sự yêu cầu.

## Phạm Vi Được Bảo Vệ

Các file sau phải giữ nguyên, trừ khi test chứng minh cần một thay đổi tương thích không liên quan thuật toán và người dùng duyệt ngoại lệ đó:

- `src/packages/agent/planning/graph.py`
- `src/packages/agent/planning/nodes/planning_nodes.py`
- `src/packages/agent/planning/tools/adaptive_station_planner.py`
- `src/packages/agent/replanning/`
- `src/packages/core/replanning/application/supervisor_loop.py`
- Mọi công thức số và ngưỡng policy của F1/F4 trong repository
- `src/packages/core/trips/application/station_graph_builder.py`
- `src/packages/core/trips/infrastructure/station_graph_repository.py`
- `src/packages/core/trips/infrastructure/station_catalog_repository.py`
- Các model/config/migration thuộc station graph hoặc station catalog

## Hành Vi Dữ Liệu Và Vòng Đời

Các nhóm plan phải được lưu nguyên tử dưới cùng một version, giữ các phương án thay thế đã xếp hạng, tách dữ liệu proposal khỏi snapshot giả định và tiếp tục đọc được định dạng legacy lồng nhau còn được hỗ trợ. Plan khả thi mới tạo vẫn ở trạng thái chờ cho tới khi người dùng xác nhận rõ ràng. Kết quả recovery có điều kiện phải giữ trạng thái có điều kiện. Chuyển đổi trạng thái trip phải phản ánh thành công lập kế hoạch hoặc lỗi provider để client sau khi tải lại nhận được trạng thái có thẩm quyền từ máy chủ.

Việc tạo và quyết định plan đồng thời phải giữ ranh giới optimistic concurrency hiện tại. Chỉ một quyết định hợp lệ được quyền nhận một version đang chờ; quyết định dùng version cũ phải nhận phản hồi conflict hiện có.

## Hành Vi Provider Và Lỗi

Mất dịch vụ provider, rate limit, bằng chứng cũ và hết phạm vi tìm kiếm phải tiếp tục được phân biệt với trường hợp đã chứng minh không khả thi. API phải trả outcome có kiểu đúng theo contract hiện tại và lưu trạng thái trip tương ứng. Điều khiển timeout/thử lại đã có trên frontend phải giữ nguyên, trừ khi test hồi quy phát hiện lỗi wiring.

## Chiến Lược Migration

Thêm một revision riêng trên nhánh F4 chỉ để khôi phục các cột persistence F2 của `plan_versions`. Revision này không tạo, khôi phục, sửa hoặc hợp nhất bất kỳ schema station graph nào. Hai head và schema station graph legacy được ghi nhận là vấn đề ngoài phạm vi theo chỉ đạo của người dùng.

## Chiến Lược Test

Quá trình triển khai theo red-green-refactor, dùng chính các test đang fail làm trạng thái đỏ ban đầu.

Thứ tự kiểm tra:

1. Chạy các module F2/planning/plan-persistence liên quan review để xác nhận RED.
2. Sửa từng cụm lỗi bằng thay đổi production nhỏ nhất rồi chạy lại test tập trung.
3. Chạy các module F3/F4 hiện có để xác nhận không hồi quy.
4. Chạy frontend test và build production.
5. Xác nhận Git diff không chứa thay đổi trong các file thuật toán, agent F1/F4 hoặc station graph được bảo vệ.

Điều kiện hoàn thành là toàn bộ test backend liên quan trực tiếp tới review pass, frontend test/build thành công và không có file được bảo vệ nào bị thay đổi. Các lỗi legacy station graph ngoài phạm vi sẽ được báo riêng, không được sửa trong task này.

## Các Phương Án Bị Loại

- **Cherry-pick nguyên khối `57e8a70` hoặc `648404f`:** bị loại vì sẽ đưa vào nhiều thay đổi không liên quan và ghi đè phần F4 mới hơn.
- **Chỉ viết lại implementation dựa trên assertion của test:** bị loại vì đã có implementation lịch sử làm tham chiếu và cần tận dụng nó để giữ đúng contract ban đầu.
- **Thay đổi hoặc xóa test đang fail:** bị loại vì các lỗi đang phản ánh trạng thái merge không đồng bộ và nhiều yêu cầu vòng đời trong review của mentor.
