// 산출물 파일의 실제 이름은 그대로 두고, 화면에는 목사님이 알아보기 쉬운
// 이름을 보여 준다. 서버(core/artifacts.py is_internal)와 같은 기준으로
// 작업용 부산물은 숨긴다 — 이미 저장된 옛 대화에도 적용되도록 여기서도 거른다.

function baseName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

function parentName(path: string): string {
  const segments = path.split(/[\\/]/);
  return segments.length > 1 ? segments[segments.length - 2] : "";
}

export function isInternalArtifact(path: string): boolean {
  const name = baseName(path).toLowerCase();
  if (name.startsWith("_") || /^gate[-_]?report/.test(name)) return true;
  return parentName(path).toLowerCase() === "sections";
}

// 작업 폴더의 관례 파일명 → 화면 이름
const KNOWN_TITLES: [RegExp, string][] = [
  [/^(design|설계서?|설계안)$/i, "설계안"],
  [/^(draft|원고|초안|원고초안)$/i, "원고 초안"],
  [/^(final|최종|최종원고)$/i, "최종 원고"],
  [/^(outline|개요)$/i, "개요"],
  [/^(series[-_ ]?plan|시리즈[-_ ]?기획)$/i, "시리즈 기획안"],
  [/^(review|검토)$/i, "검토 의견"],
];

export function displayTitle(fileName: string): string {
  const name = baseName(fileName);
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  for (const [pattern, title] of KNOWN_TITLES) {
    if (pattern.test(stem)) return title;
  }
  // "2026-10-04_아직-감옥이-끝이-아니다" → "원고 · 아직 감옥이 끝이 아니다"
  const dated = stem.match(/^\d{4}-\d{2}-\d{2}[_ -]+(.+)$/);
  const words = (dated ? dated[1] : stem).replace(/[_-]+/g, " ").trim();
  if (!words) return name;
  return dated && /[가-힣]/.test(words) ? `원고 · ${words}` : words;
}
