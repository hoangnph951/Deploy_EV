import { useEffect, useRef, useState } from "react";

import { autocompletePlaces, getPlaceDetail } from "../lib/api";
import type { PlacePrediction, PlaceSelection } from "../lib/types";

type Props = {
  id: string;
  value: string;
  placeholder: string;
  onTextChange: (value: string) => void;
  onPlaceSelect: (place: PlaceSelection) => void;
};

function newSessionToken(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function GoongPlaceInput({ id, value, placeholder, onTextChange, onPlaceSelect }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const sessionTokenRef = useRef(newSessionToken());
  const skipSearchRef = useRef(false);
  const [predictions, setPredictions] = useState<PlacePrediction[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [noResults, setNoResults] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  useEffect(() => {
    if (skipSearchRef.current) {
      skipSearchRef.current = false;
      return;
    }
    const query = value.trim();
    if (query.length < 2) {
      setPredictions([]);
      setOpen(false);
      setLoadError("");
      setNoResults(false);
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      autocompletePlaces(query, sessionTokenRef.current, controller.signal)
        .then((response) => {
          setPredictions(response.predictions);
          setNoResults(response.predictions.length === 0);
          setOpen(true);
          setActiveIndex(-1);
          setLoadError("");
        })
        .catch((error) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          setPredictions([]);
          setOpen(false);
          setNoResults(false);
          setLoadError(error instanceof Error ? error.message : "Không tải được gợi ý từ Goong.");
        })
        .finally(() => setLoading(false));
    }, 300);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [value]);

  useEffect(() => {
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, []);

  const selectPrediction = async (prediction: PlacePrediction) => {
    setLoading(true);
    setLoadError("");
    setNoResults(false);
    setOpen(false);
    try {
      const detail = await getPlaceDetail(prediction.place_id, sessionTokenRef.current);
      const address = detail.formatted_address || detail.name || prediction.description;
      skipSearchRef.current = true;
      onTextChange(address);
      onPlaceSelect({
        address,
        lat: detail.lat,
        lng: detail.lng,
        placeId: detail.place_id,
      });
      sessionTokenRef.current = newSessionToken();
      setPredictions([]);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Không lấy được tọa độ từ Goong.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div ref={rootRef} className="goong-place-field">
      <div className="goong-place-input-wrap">
        <input
          id={id}
          className="goong-place-input"
          value={value}
          placeholder={placeholder}
          autoComplete="off"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={`${id}-suggestions`}
          onFocus={() => setOpen(predictions.length > 0 || noResults)}
          onChange={(event) => {
            setNoResults(false);
            onTextChange(event.target.value);
          }}
          onKeyDown={(event) => {
            if (!open || predictions.length === 0) return;
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActiveIndex((current) => Math.min(current + 1, predictions.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActiveIndex((current) => Math.max(current - 1, 0));
            } else if (event.key === "Enter" && activeIndex >= 0) {
              event.preventDefault();
              void selectPrediction(predictions[activeIndex]);
            } else if (event.key === "Escape") {
              setOpen(false);
            }
          }}
        />
        <span className="place-input-status" aria-hidden="true">{loading ? "…" : "⌕"}</span>
      </div>

      {open ? (
        <div id={`${id}-suggestions`} className="goong-suggestion-list" role="listbox">
          {noResults ? (
            <div className="goong-suggestion-empty" role="status">Không tìm thấy địa điểm.</div>
          ) : null}
          {predictions.map((prediction, index) => (
            <button
              key={prediction.place_id}
              type="button"
              role="option"
              aria-selected={index === activeIndex}
              className={`goong-suggestion-item${index === activeIndex ? " is-active" : ""}`}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => void selectPrediction(prediction)}
            >
              <span className="suggestion-pin" aria-hidden="true">●</span>
              <span>
                <strong>{prediction.main_text || prediction.description}</strong>
                <small>{prediction.secondary_text}</small>
              </span>
            </button>
          ))}
          <small className="goong-attribution">Dữ liệu địa điểm từ Goong</small>
        </div>
      ) : null}
      {loadError ? <small className="field-error">{loadError}</small> : null}
    </div>
  );
}
