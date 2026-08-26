import { useEffect, useMemo, useState, type FormEvent } from "react";

import { addMyVehicle, ApiError } from "../lib/api";
import type { UserVehicle, VehicleProfileSnapshot } from "../lib/types";

export function VehicleSetup({
  profiles,
  canCancel,
  onComplete,
  onCancel,
}: {
  profiles: VehicleProfileSnapshot[];
  canCancel: boolean;
  onComplete: (vehicle: UserVehicle) => void;
  onCancel: () => void;
}) {
  const [profileId, setProfileId] = useState(profiles[0]?.id ?? "");
  const [nickname, setNickname] = useState("");
  const [licensePlate, setLicensePlate] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!profileId && profiles[0]) setProfileId(profiles[0].id);
  }, [profileId, profiles]);
  const profile = useMemo(() => profiles.find((item) => item.id === profileId) ?? profiles[0], [profileId, profiles]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!profile) return;
    setSubmitting(true);
    setError("");
    try {
      onComplete(await addMyVehicle({
        vehicle_profile_id: profile.id,
        nickname: nickname || null,
        license_plate: licensePlate || null,
        make_default: true,
      }));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.payload.error.message : "Không thể lưu xe lúc này.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="vehicle-onboarding">
      <section className="vehicle-setup-card">
        <div className="vehicle-setup-icon">EV</div>
        <header><small>BƯỚC THIẾT LẬP XE</small><h1>Xe của bạn</h1><p>Chọn đúng phiên bản để hệ thống dùng dung lượng pin, chuẩn sạc và giới hạn công suất phù hợp.</p></header>
        <form onSubmit={submit}>
          <label><span>Mẫu xe</span><select value={profileId} onChange={(event) => setProfileId(event.target.value)} required>{profiles.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
          <div className="vehicle-personal-fields">
            <label><span>Tên gợi nhớ <small>(tùy chọn)</small></span><input value={nickname} onChange={(event) => setNickname(event.target.value)} placeholder="Ví dụ: VF 6 của Minh" /></label>
            <label><span>Biển số <small>(tùy chọn)</small></span><input value={licensePlate} onChange={(event) => setLicensePlate(event.target.value.toUpperCase())} placeholder="30A-123.45" /></label>
          </div>
          {profile ? (
            <div className="vehicle-profile-preview">
              <div><span>Pin khả dụng</span><strong>{profile.usable_capacity_kwh} kWh</strong></div>
              <div><span>Chuẩn sạc</span><strong>{profile.connector_type}</strong></div>
              <div><span>Sạc DC tối đa</span><strong>{profile.max_charging_power_kw} kW</strong></div>
              <div>
                <span>Range tham chiếu</span>
                <strong>{profile.reference_range_km ?? "—"} km {profile.reference_range_standard ?? ""}</strong>
              </div>
            </div>
          ) : <p>Đang tải danh mục xe…</p>}
          <p className="vehicle-source-note">
            Thông số kỹ thuật lấy từ profile VinFast theo đúng phiên bản và không cho sửa tay để tránh tính SOC sai.{" "}
            {profile?.official_source_url ? <a href={profile.official_source_url} target="_blank" rel="noreferrer">Kiểm tra nguồn chính hãng ↗</a> : null}
          </p>
          {error ? <div className="auth-error">{error}</div> : null}
          <button className="auth-submit" disabled={submitting || !profile} type="submit">{submitting ? "Đang lưu…" : "Lưu xe và lập hành trình"}</button>
          {canCancel ? <button className="vehicle-cancel" type="button" onClick={onCancel}>Quay lại kế hoạch</button> : null}
        </form>
      </section>
    </main>
  );
}
