// 사용자가 고르는 글꼴 목록. id는 core/settings.py 의 _ALLOWED 목록과 같아야 한다.
// 모든 글꼴은 앱에 번들되어 오프라인에서도 동작하고, 고른 글꼴의 CSS만 그때 불러온다.

// 시스템 기본 — 번들 글꼴 이름을 섞지 않아야 '시스템 기본'이 정말 시스템 글꼴로 돌아간다
const SANS = `-apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Malgun Gothic", "맑은 고딕", "Segoe UI", system-ui, sans-serif`;
const SERIF = `"AppleMyungjo", Batang, "바탕", Georgia, serif`;

export type FontOption = {
  id: string;
  label: string;
  stack: string;
  load?: () => Promise<unknown>;
};

export const BODY_FONTS: FontOption[] = [
  { id: "system", label: "시스템 기본", stack: SANS },
  { id: "pretendard", label: "Pretendard", stack: `"Pretendard", ${SANS}`,
    load: () => Promise.all([import("@fontsource/pretendard/400.css"), import("@fontsource/pretendard/700.css")]) },
  { id: "suit", label: "SUIT", stack: `"SUIT", ${SANS}`,
    load: () => import("./fonts/suit.css") },
  { id: "ibm-plex-sans-kr", label: "IBM Plex Sans KR", stack: `"IBM Plex Sans KR", ${SANS}`,
    load: () => Promise.all([import("@fontsource/ibm-plex-sans-kr/400.css"), import("@fontsource/ibm-plex-sans-kr/700.css")]) },
  { id: "nanum-gothic", label: "나눔고딕", stack: `"Nanum Gothic", ${SANS}`,
    load: () => Promise.all([import("@fontsource/nanum-gothic/400.css"), import("@fontsource/nanum-gothic/700.css")]) },
];

export const HEADING_FONTS: FontOption[] = [
  { id: "system", label: "시스템 명조", stack: SERIF },
  { id: "maruburi", label: "마루 부리", stack: `"MaruBuri", ${SERIF}`,
    load: () => import("./fonts/maruburi.css") },
  { id: "gowun-batang", label: "고운바탕", stack: `"Gowun Batang", ${SERIF}`,
    load: () => Promise.all([import("@fontsource/gowun-batang/400.css"), import("@fontsource/gowun-batang/700.css")]) },
  { id: "noto-serif-kr", label: "Noto Serif KR", stack: `"Noto Serif KR", ${SERIF}`,
    load: () => Promise.all([import("@fontsource/noto-serif-kr/400.css"), import("@fontsource/noto-serif-kr/700.css")]) },
  { id: "nanum-myeongjo", label: "나눔명조", stack: `"Nanum Myeongjo", ${SERIF}`,
    load: () => Promise.all([import("@fontsource/nanum-myeongjo/400.css"), import("@fontsource/nanum-myeongjo/700.css")]) },
  { id: "hahmlet", label: "함렡", stack: `"Hahmlet", ${SERIF}`,
    load: () => Promise.all([import("@fontsource/hahmlet/400.css"), import("@fontsource/hahmlet/700.css")]) },
];

function pick(list: FontOption[], id: string | undefined): FontOption {
  return list.find(f => f.id === id) ?? list[0];
}

/** 글꼴 CSS를 불러온 뒤 화면 전체의 --sans / --serif 를 바꾼다(불러오기 전에 바꾸면 깜빡인다). */
export async function applyFonts(bodyId?: string, headingId?: string): Promise<void> {
  const body = pick(BODY_FONTS, bodyId);
  const heading = pick(HEADING_FONTS, headingId);
  await Promise.all([body.load?.(), heading.load?.()].map(p => p?.catch(() => undefined)));
  const root = document.documentElement.style;
  root.setProperty("--sans", body.stack);
  root.setProperty("--serif", heading.stack);
}
