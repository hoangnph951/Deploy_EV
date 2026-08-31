import assert from "node:assert/strict";
import test from "node:test";

import {
  labelAction,
  labelHypothesis,
  labelObjective,
  labelStage,
  labelStatus,
  labelTool,
  labelTraceKind,
} from "./replanningPresentation.ts";


test("decision stages are presented in Vietnamese", () => {
  assert.equal(labelStage("ASSESSING"), "Đang xác định tình huống");
  assert.equal(labelStage("DIAGNOSING"), "Đang kiểm tra dữ liệu");
  assert.equal(labelStage("REFLECTING"), "Đang đánh giá bằng chứng");
  assert.equal(labelStage("PROPOSING_ACTION"), "Đang chuẩn bị đề xuất");
});


test("machine outcomes have understandable Vietnamese labels", () => {
  assert.equal(labelStatus("INSUFFICIENT_EVIDENCE"), "Chưa đủ dữ liệu an toàn");
  assert.equal(labelHypothesis("UNCERTAIN"), "Chưa đủ bằng chứng để kết luận");
  assert.equal(labelAction("PROPOSE_REPLAN"), "Đề xuất hành trình thay thế");
  assert.equal(labelTool("build_f1_candidate"), "Tạo phương án hành trình mới");
  assert.equal(labelTool("build_minimal_substitution"), "Thử thay thế tối thiểu trạm không khả dụng");
  assert.equal(labelTool("build_full_replan"), "Lập lại toàn bộ phần hành trình còn lại");
  assert.equal(labelObjective("PROTECT_RESERVE_SOC"), "Bảo vệ mức pin dự phòng");
  assert.equal(
    labelTool("nearest_station_reachability"),
    "Kiểm tra trạm sạc gần nhất có thể tiếp cận",
  );
});


test("trace labels distinguish GPT output from deterministic fallback", () => {
  assert.equal(labelTraceKind("REFLECTING", "OPENAI"), "Phản ánh của GPT");
  assert.equal(
    labelTraceKind("REFLECTING", "SAFE_FALLBACK"),
    "Phản hồi an toàn dự phòng",
  );
  assert.equal(labelTraceKind("DIAGNOSING", "DETERMINISTIC"), "Quan sát từ công cụ");
  assert.equal(labelTraceKind("GUARDING_ACTION", "DETERMINISTIC"), "Bước điều phối");
});
