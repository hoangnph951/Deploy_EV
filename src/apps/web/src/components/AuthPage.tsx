import { useState, type FormEvent } from "react";

import { ApiError, loginAccount, registerAccount, saveAccessToken } from "../lib/api";
import type { AuthTokenResponse } from "../lib/types";

type AuthMode = "login" | "register";

export function AuthPage({ onAuthenticated }: { onAuthenticated: (result: AuthTokenResponse) => void }) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const switchMode = (nextMode: AuthMode) => {
    setMode(nextMode);
    setError("");
    setPassword("");
    setConfirmation("");
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const result = mode === "register"
        ? await registerAccount({
          full_name: fullName,
          email,
          phone: phone || null,
          password,
          password_confirmation: confirmation,
          accepted_terms: acceptedTerms,
        })
        : await loginAccount({ email, password, remember_me: rememberMe });
      saveAccessToken(result.access_token, mode === "login" && rememberMe);
      onAuthenticated(result);
    } catch (caught) {
      if (caught instanceof ApiError) {
        const validation = caught.payload.error.details?.errors?.[0]?.msg;
        setError(validation ?? caught.payload.error.message);
      } else {
        setError("Không thể kết nối máy chủ. Vui lòng thử lại.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-hero" aria-label="Giới thiệu VGo">
        <div className="auth-brand"><img src="/logo.png" alt="VGo" /></div>
        <div className="auth-hero-copy">
          <h1>{mode === "register" ? <>Bắt đầu hành trình<br />EV thông minh.<br /><em>Tạo tài khoản trong vài phút.</em></> : <>Lên kế hoạch. Sạc thông minh.<br /><em>Di chuyển bền vững.</em></>}</h1>
          <p>VGo giúp bạn lập kế hoạch hành trình cho xe điện bằng tuyến đường, trạm sạc và dữ liệu môi trường đã ghi rõ nguồn.</p>
          <div className="auth-benefits">
            <div><span>⌖</span><p><strong>Kế hoạch tối ưu</strong><small>Tuyến, SOC và điểm sạc phù hợp cho xe của bạn.</small></p></div>
            <div><span>ϟ</span><p><strong>Trạm sạc đáng tin cậy</strong><small>Metadata trạm được xác minh qua VinFast Locator.</small></p></div>
            <div><span>▥</span><p><strong>Minh bạch dữ liệu</strong><small>Phân biệt rõ dữ liệu live và giá trị mô hình.</small></p></div>
          </div>
        </div>
        <div className="auth-road" aria-hidden="true"><i /><span className="road-pin road-pin--one">ϟ</span><span className="road-pin road-pin--two">ϟ</span><b>EV</b></div>
      </section>

      <section className="auth-form-side">
        <form className="auth-card" onSubmit={submit}>
          <header><h2>{mode === "register" ? "Đăng ký" : "Đăng nhập"}</h2><p>{mode === "register" ? "Tạo tài khoản để lưu xe và bắt đầu lập kế hoạch." : "Chào mừng bạn quay lại VGo"}</p></header>

          {mode === "register" ? (
            <label><span>Họ và tên</span><div className="auth-input"><i>♙</i><input required minLength={2} value={fullName} onChange={(event) => setFullName(event.target.value)} placeholder="Nhập họ và tên của bạn" autoComplete="name" /></div></label>
          ) : null}
          <label><span>Email</span><div className="auth-input"><i>✉</i><input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="Nhập email của bạn" autoComplete="email" /></div></label>
          {mode === "register" ? (
            <label><span>Số điện thoại <small>(tùy chọn)</small></span><div className="auth-input"><i>⌕</i><input value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="Nhập số điện thoại của bạn" autoComplete="tel" /></div></label>
          ) : null}
          <label><span>Mật khẩu</span><div className="auth-input"><i>▣</i><input required minLength={mode === "register" ? 8 : 1} type={showPassword ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Nhập mật khẩu của bạn" autoComplete={mode === "register" ? "new-password" : "current-password"} /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label="Hiện hoặc ẩn mật khẩu">◉</button></div>{mode === "register" ? <small className="password-hint">Tối thiểu 8 ký tự, gồm chữ hoa, chữ thường và chữ số.</small> : null}</label>
          {mode === "register" ? (
            <label><span>Xác nhận mật khẩu</span><div className="auth-input"><i>▣</i><input required minLength={8} type={showPassword ? "text" : "password"} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder="Nhập lại mật khẩu của bạn" autoComplete="new-password" /></div></label>
          ) : null}

          {mode === "register" ? (
            <label className="auth-check"><input type="checkbox" checked={acceptedTerms} onChange={(event) => setAcceptedTerms(event.target.checked)} /><span>Tôi đồng ý với <a href="#terms">Điều khoản sử dụng</a> và <a href="#privacy">Chính sách bảo mật</a>.</span></label>
          ) : (
            <div className="auth-options"><label className="auth-check"><input type="checkbox" checked={rememberMe} onChange={(event) => setRememberMe(event.target.checked)} /><span>Ghi nhớ đăng nhập</span></label><span>Phiên thường: 24 giờ</span></div>
          )}

          {error ? <div className="auth-error" role="alert">{error}</div> : null}
          <button className="auth-submit" disabled={submitting} type="submit">{submitting ? "Đang xử lý…" : mode === "register" ? "Tạo tài khoản" : "Đăng nhập"}</button>

          <div className="auth-divider"><span>Hoặc</span></div>
          <button className="social-button" type="button" disabled><strong>G</strong> Google <small>Chưa cấu hình</small></button>
          <button className="social-button" type="button" disabled><strong>⊞</strong> Microsoft <small>Chưa cấu hình</small></button>
          <p className="auth-switch">{mode === "register" ? "Đã có tài khoản?" : "Chưa có tài khoản?"} <button type="button" onClick={() => switchMode(mode === "register" ? "login" : "register")}>{mode === "register" ? "Đăng nhập" : "Đăng ký"}</button></p>
        </form>
        <p className="auth-security">♢ Mật khẩu được băm PBKDF2; token phiên có thể bị thu hồi khi đăng xuất.</p>
      </section>
    </main>
  );
}
