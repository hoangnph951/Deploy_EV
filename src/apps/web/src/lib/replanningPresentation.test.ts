import assert from "node:assert/strict";
import test from "node:test";

import * as presentation from "./replanningPresentation.ts";
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


test("simulated incident marker exposes its coordinates", () => {
  const marker = (
    presentation as typeof presentation & {
      simulatedIncidentMarker?: (lat: number, lon: number) => {
        title: string;
        coordinateLine: string;
      };
    }
  ).simulatedIncidentMarker?.(20.812345, 105.678912);

  assert.deepEqual(marker, {
    title: "Vị trí sự cố mô phỏng",
    coordinateLine: "Tọa độ 20.81235, 105.67891",
  });
});


test("live trace heading separates the stage from the tool label", () => {
  const heading = (
    presentation as typeof presentation & {
      traceHeading?: (stage: string, tool?: string | null) => string;
    }
  ).traceHeading?.("REFLECTING", "project_current_plan");

  assert.equal(
    heading,
    "Đang đánh giá bằng chứng\nĐánh giá phần hành trình còn lại",
  );
});


test("public evidence summary never exposes internal reference identifiers", () => {
  const summary = (
    presentation as typeof presentation & {
      publicEvidenceSummary?: (
        evidenceRefs: string[],
        excludedStationIds: string[],
      ) => { evidenceNotice: string; excludedStationsNotice: string };
    }
  ).publicEvidenceSummary?.(
    [
      "plan:b4047925-b0c2-4e81-9e39-afff747b3303:v1",
      "telemetry:49f40e26-3cfc-47c0-8c73-5cfcae3c5cba",
      "station:C.HNO0427:excluded",
    ],
    ["C.HNO0427"],
  );

  assert.deepEqual(summary, {
    evidenceNotice: "Bằng chứng an toàn đã được hệ thống kiểm tra nội bộ.",
    excludedStationsNotice: "1 trạm không khả dụng đã được loại khỏi phương án.",
  });
  assert.doesNotMatch(JSON.stringify(summary), /b4047925|49f40e26|C\.HNO0427/);
});
