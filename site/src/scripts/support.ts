const supportRelay = "https://relay.beacontools.cc";
export {};

type SupportPayload = { ok?: boolean; detail?: string; message?: string };

function setStatus(form: HTMLFormElement, text: string, tone = ""): void {
  const target = form.querySelector<HTMLElement>(".form-status");
  if (!target) return;
  target.textContent = text;
  target.dataset.tone = tone;
}

function disableForm(form: HTMLFormElement, disabled: boolean): void {
  form.querySelectorAll<HTMLInputElement | HTMLButtonElement | HTMLSelectElement | HTMLTextAreaElement>("button, input, select, textarea").forEach((element) => {
    if (!element.classList.contains("honeypot")) element.disabled = disabled;
  });
}

async function responsePayload(response: Response): Promise<SupportPayload> {
  return response.json().catch(() => ({})) as Promise<SupportPayload>;
}

async function submitContact(formData: FormData): Promise<string> {
  const data = Object.fromEntries(formData.entries());
  const response = await fetch(`${supportRelay}/v1/site/contact`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(data),
  });
  const payload = await responsePayload(response);
  if (!response.ok || !payload.ok) throw new Error(payload.detail || payload.message || "We could not send your question. Please try again.");
  return payload.message || "Your question was sent.";
}

async function submitBug(formData: FormData): Promise<string> {
  const response = await fetch(`${supportRelay}/v1/site/bug-report`, {
    method: "POST",
    body: formData,
  });
  const payload = await responsePayload(response);
  if (!response.ok || !payload.ok) throw new Error(payload.detail || payload.message || "We could not send the issue report. Please try again.");
  return payload.message || "Your issue report was sent.";
}

document.querySelectorAll<HTMLFormElement>("[data-support-form]").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setStatus(form, "Sending…");
    const formData = new FormData(form);
    disableForm(form, true);
    try {
      const message = form.dataset.supportForm === "contact" ? await submitContact(formData) : await submitBug(formData);
      form.reset();
      setStatus(form, message, "ok");
    } catch (error) {
      const message = error instanceof Error && error.message ? error.message : "We could not send this form. Please try again.";
      setStatus(form, message, "bad");
    } finally {
      disableForm(form, false);
    }
  });
});
