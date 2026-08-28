const labels = {
  ASSESSING: "Đang xác định tình huống",
  DIAGNOSING: "Đang kiểm tra dữ liệu",
  REFLECTING: "Đang đánh giá bằng chứng",
  BUILDING_CANDIDATE: "Đang tạo phương án mới",
  COMPARING_PLANS: "Đang so sánh các hành trình",
  PROPOSING_ACTION: "Đang chuẩn bị đề xuất",
  GUARDING_ACTION: "Đang kiểm tra quy tắc an toàn",
  SUCCEEDED: "Đã hoàn thành",
  BLOCKED: "Bị chặn bởi quy tắc an toàn",
  FAILED: "Không hoàn thành",
  INFEASIBLE: "Không có phương án khả thi",
  INSUFFICIENT_EVIDENCE: "Chưa đủ dữ liệu an toàn",
  SEARCH_EXHAUSTED: "Đã hết phạm vi tìm kiếm",
  FEASIBLE: "Phương án đáp ứng điều kiện an toàn",
  SUPPORTED: "Bằng chứng ủng hộ phương án",
  REJECTED: "Bằng chứng bác bỏ phương án",
  UNCERTAIN: "Chưa đủ bằng chứng để kết luận",
  PROPOSE_REPLAN: "Đề xuất hành trình thay thế",
  REQUEST_NEW_TELEMETRY: "Yêu cầu dữ liệu xe mới",
  STOP_INSUFFICIENT_EVIDENCE: "Dừng vì chưa đủ bằng chứng",
  NO_FEASIBLE_PLAN_REQUEST_ASSISTANCE: "Yêu cầu hỗ trợ vì chưa có hành trình an toàn",
  inspect_telemetry: "Kiểm tra vị trí và mức pin hiện tại",
  project_current_plan: "Đánh giá phần hành trình còn lại",
  inspect_route: "Kiểm tra tuyến đường",
  inspect_energy: "Kiểm tra mức tiêu thụ và dự phòng pin",
  nearest_station_reachability: "Kiểm tra trạm sạc gần nhất có thể tiếp cận",
  inspect_stations: "Kiểm tra trạm sạc và danh sách loại trừ",
  build_f1_candidate: "Tạo phương án hành trình mới",
  build_minimal_substitution: "Thử thay thế tối thiểu trạm không khả dụng",
  build_full_replan: "Lập lại toàn bộ phần hành trình còn lại",
  compare_plans: "So sánh phương án hiện tại và phương án mới",
} as const;

function label(code: string): string {
  return labels[code as keyof typeof labels] ?? `Mã kỹ thuật: ${code}`;
}

export const labelStage = label;
export const labelStatus = label;
export const labelHypothesis = label;
export const labelAction = label;
export const labelTool = label;

export function labelObjective(code: string): string {
  const objectives: Record<string, string> = {
    RESTORE_SAFE_ROUTE: "Khôi phục lộ trình an toàn",
    PROTECT_RESERVE_SOC: "Bảo vệ mức pin dự phòng",
    REPLACE_UNAVAILABLE_STATION: "Thay thế trạm không khả dụng",
    RECOVER_TELEMETRY: "Khôi phục dữ liệu xe",
    PRESERVE_CURRENT_PLAN: "Giữ lộ trình hiện tại",
    COMPOSITE_RECOVERY: "Xử lý đồng thời nhiều rủi ro",
  };
  return objectives[code] ?? label(code);
}

export function explainReasonCode(code: string): string {
  const explanations: Record<string, string> = {
    TELEMETRY_VERIFIED: "Dữ liệu vị trí và mức pin còn hiệu lực.",
    TELEMETRY_BLOCKED: "Dữ liệu vị trí hoặc mức pin đã cũ, không được dùng để tính tuyến.",
    CURRENT_PLAN_PROJECTED: "Đã đánh giá phần còn lại của hành trình đang được xác nhận.",
    UNAVAILABLE_STATION_AFFECTS_REMAINING_TRIP: "Trạm không khả dụng vẫn nằm trong phần hành trình phía trước.",
    UNAVAILABLE_STATION_NOT_IN_REMAINING_TRIP: "Trạm không khả dụng không còn ảnh hưởng phần hành trình phía trước.",
    MINIMAL_SUBSTITUTION_NOT_SATISFIED: "Không tìm được phương án chỉ thay đổi tối thiểu; cần lập lại toàn bộ.",
    ROUTE_EVIDENCE_VERIFIED: "Đã kiểm tra dữ liệu tuyến đường cho vị trí hiện tại.",
    ENERGY_EVIDENCE_VERIFIED: "Đã tính lại mức pin và biên dự phòng.",
    STATION_EXCLUSIONS_VERIFIED: "Các trạm không khả dụng đã được loại khỏi phạm vi tìm kiếm.",
    DETERMINISTIC_FEASIBILITY: "Tính khả thi được xác nhận bằng bộ tính toán an toàn.",
    PLAN_COMPARISON_COMPLETED: "Đã hoàn tất so sánh hai hành trình.",
    CANDIDATE_FEASIBLE: "Phương án mới vượt qua kiểm tra khả thi.",
  };
  return explanations[code] ?? `Chi tiết kỹ thuật: ${code}`;
}
