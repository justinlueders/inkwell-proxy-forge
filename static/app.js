"use strict";

const API_ROUTES = Object.freeze({
  CONFIG: "/api/config",
  SHEET: "/api/sheet",
  IMPORT: "/api/import",
});

const CONFIG = Object.freeze({
  JPEG_DATA_URL_PREFIX: "data:image/jpeg;base64,",
  JSON_CONTENT_TYPE: "application/json",
  CONTENT_TYPE_HEADER: "Content-Type",
  ACCEPT_HEADER: "Accept",
  REQUEST_ID_HEADER: "X-Request-ID",
  POST_METHOD: "POST",
  ABORT_ERROR_NAME: "AbortError",
  REQUESTS_PER_CARD: 2,
  ESTIMATED_NETWORK_SECONDS_PER_CARD: 0.6,
  ESTIMATED_RENDER_SECONDS_PER_PAGE: 1,
  TIMEOUT_BUFFER_SECONDS: 30,
  MS_PER_SECOND: 1000,
  NUMERIC_PATTERN: /^[0-9]+$/,
  LEADING_ZEROS_PATTERN: /^0+(?=\d)/,
  KEY_SEPARATOR: "/",
  ABORT_REASON_TIMEOUT: "timeout",
  ABORT_REASON_CANCEL: "cancel",
  FIRST_PAGE_INDEX: 0,
  ESTIMATED_NETWORK_SECONDS_PER_SEARCH: 0.3,
  MAX_SEARCHES_PER_IMPORT_LINE: 2,
  LINE_BREAK_PATTERN: /\r\n|\r|\n/,
  LINE_BREAK: "\n",
});

const MESSAGES = Object.freeze({
  CONFIG_FAILED: "Could not reach the server. Make sure it is running, then reload the page.",
  REQUIRED: "Required",
  TOO_LONG: (max) => `At most ${max} characters`,
  QUANTITY_RANGE: (min, max) => `Whole number from ${min} to ${max}`,
  CARD_QUANTITY_CAP: (max) => `That card would exceed ${max} copies`,
  TOTAL_CAP: (max) => `A sheet holds at most ${max} cards`,
  ENTRY_CAP: (max) => `At most ${max} different cards per sheet`,
  OVER_LIMIT: (total, max) => `${total} cards is over the ${max}-card limit. Remove some to continue.`,
  WORKING: (seconds) => `Fetching card art and forging pages... about ${seconds}s`,
  NETWORK_TITLE: "Could not reach the server",
  NETWORK_DETAIL: "Check that the server is running and try again.",
  TIMEOUT_TITLE: "The request took too long",
  TIMEOUT_DETAIL: "Lorcast may be slow right now. Try again or print fewer cards.",
  CANCELLED_TITLE: "Generation cancelled",
  BAD_JSON_TITLE: "The server sent an unreadable response",
  HTTP_TITLE: (status) => `The server returned an error (HTTP ${status})`,
  PARTIAL_TITLE: (count) =>
    count === 1
      ? "1 card could not be fetched and is shown as a placeholder"
      : `${count} cards could not be fetched and are shown as placeholders`,
  CARD_UNIT: (count) => (count === 1 ? "card" : "cards"),
  PAGE_UNIT: (count) => (count === 1 ? "page" : "pages"),
  ALL_FAILED_TITLE: "None of the cards could be fetched",
  CARD_ERROR: (error) => `Set ${error.set_code} card ${error.number}: ${error.detail}`,
  PRINT_FAILED_TITLE: "The pages could not be prepared for printing",
  REQUEST_ID: (id) => `Request id: ${id}`,
  PAGE_COUNTER: (current, total) => `Page ${current} of ${total}`,
  PAGE_ALT: (current, total) => `Proxy sheet page ${current} of ${total}`,
  IMPORT_EMPTY: "Paste at least one line, e.g. 4 Hercules - Spectral Demigod",
  IMPORT_TOO_LONG: (max) => `The deck list is too long; the limit is ${max} characters`,
  IMPORT_TOO_MANY_LINES: (count, max) => `${count} lines is over the ${max}-line limit`,
  IMPORT_WORKING: (seconds) => `Looking up cards on Lorcast... about ${seconds}s`,
  IMPORT_DONE: (added, copies) =>
    `Imported ${added} ${added === 1 ? "card" : "cards"} (${copies} ${copies === 1 ? "copy" : "copies"})`,
  IMPORT_PARTIAL_TITLE: (added, problems) =>
    `Imported ${added} ${added === 1 ? "card" : "cards"}; ${problems} ${problems === 1 ? "line needs" : "lines need"} attention`,
  IMPORT_FAILED_TITLE: "No cards were imported",
  IMPORT_ISSUE: (issue) => `Line ${issue.line_number}: ${issue.line} - ${issue.detail}`,
  IMPORT_SKIPPED: (label, reason) => `${label} skipped: ${reason}`,
  IMPORTED_CARD_LABEL: (setCode, number, name) => `Set ${setCode} #${number} ${name}`,
});

const state = {
  limits: null,
  entries: [],
  pages: [],
  pageIndex: CONFIG.FIRST_PAGE_INDEX,
  controller: null,
  importOperation: null,
};

const dom = {
  form: document.getElementById("card-form"),
  formFields: document.getElementById("card-form-fields"),
  setInput: document.getElementById("set-input"),
  numberInput: document.getElementById("number-input"),
  quantityInput: document.getElementById("quantity-input"),
  setError: document.getElementById("set-error"),
  numberError: document.getElementById("number-error"),
  quantityError: document.getElementById("quantity-error"),
  list: document.getElementById("card-list"),
  emptyList: document.getElementById("empty-list"),
  clearButton: document.getElementById("clear-button"),
  summaryCards: document.getElementById("summary-cards"),
  summaryPages: document.getElementById("summary-pages"),
  summaryCardsUnit: document.getElementById("summary-cards-unit"),
  summaryPagesUnit: document.getElementById("summary-pages-unit"),
  limitWarning: document.getElementById("limit-warning"),
  generateButton: document.getElementById("generate-button"),
  cancelButton: document.getElementById("cancel-button"),
  progress: document.getElementById("progress"),
  progressText: document.getElementById("progress-text"),
  errorPanel: document.getElementById("error-panel"),
  errorTitle: document.getElementById("error-title"),
  errorList: document.getElementById("error-list"),
  errorRequestId: document.getElementById("error-request-id"),
  errorDismiss: document.getElementById("error-dismiss"),
  viewer: document.getElementById("viewer"),
  viewerEmpty: document.getElementById("viewer-empty"),
  viewerImage: document.getElementById("viewer-image"),
  pageCounter: document.getElementById("page-counter"),
  prevPage: document.getElementById("prev-page"),
  nextPage: document.getElementById("next-page"),
  printButton: document.getElementById("print-button"),
  printRoot: document.getElementById("print-root"),
  importOpenButton: document.getElementById("import-open-button"),
  importStatus: document.getElementById("import-status"),
  importDialog: document.getElementById("import-dialog"),
  importForm: document.getElementById("import-form"),
  importText: document.getElementById("import-text"),
  importTextError: document.getElementById("import-text-error"),
  importProgress: document.getElementById("import-progress"),
  importProgressText: document.getElementById("import-progress-text"),
  importIssues: document.getElementById("import-issues"),
  importIssuesTitle: document.getElementById("import-issues-title"),
  importIssueList: document.getElementById("import-issue-list"),
  importRequestId: document.getElementById("import-request-id"),
  importSubmitButton: document.getElementById("import-submit-button"),
  importCancelButton: document.getElementById("import-cancel-button"),
  rowTemplate: document.getElementById("card-row-template"),
  errorItemTemplate: document.getElementById("error-item-template"),
};

// --- Normalization (mirrors server/normalization.py) -------------------------

function normalizeIdentifier(value) {
  const trimmed = value.trim();
  return CONFIG.NUMERIC_PATTERN.test(trimmed) ? trimmed.replace(CONFIG.LEADING_ZEROS_PATTERN, "") : trimmed;
}

function entryKey(setCode, number) {
  return `${setCode.toLowerCase()}${CONFIG.KEY_SEPARATOR}${number}`;
}

function parseQuantity(raw) {
  const text = String(raw).trim();
  if (!CONFIG.NUMERIC_PATTERN.test(text)) {
    return null;
  }
  const value = Number.parseInt(text, 10);
  return value >= state.limits.min_quantity && value <= state.limits.max_quantity ? value : null;
}

// --- Derived values ----------------------------------------------------------

function totalCards() {
  return state.entries.reduce((sum, entry) => sum + entry.quantity, 0);
}

function pageCountFor(cards) {
  return Math.ceil(cards / state.limits.cards_per_page);
}

function estimateSeconds() {
  const perCard = CONFIG.REQUESTS_PER_CARD * state.limits.request_delay_seconds + CONFIG.ESTIMATED_NETWORK_SECONDS_PER_CARD;
  const rendering = pageCountFor(totalCards()) * CONFIG.ESTIMATED_RENDER_SECONDS_PER_PAGE;
  return Math.ceil(state.entries.length * perCard + rendering);
}

// --- Form validation ---------------------------------------------------------

function setFieldError(input, errorElement, message) {
  errorElement.textContent = message;
  if (message) {
    input.setAttribute("aria-invalid", "true");
  } else {
    input.removeAttribute("aria-invalid");
  }
}

function validateIdentifier(input, errorElement) {
  const value = normalizeIdentifier(input.value);
  if (!value) {
    setFieldError(input, errorElement, MESSAGES.REQUIRED);
    return null;
  }
  if (value.length > state.limits.max_identifier_length) {
    setFieldError(input, errorElement, MESSAGES.TOO_LONG(state.limits.max_identifier_length));
    return null;
  }
  setFieldError(input, errorElement, "");
  return value;
}

function validateForm() {
  const setCode = validateIdentifier(dom.setInput, dom.setError);
  const number = validateIdentifier(dom.numberInput, dom.numberError);
  const quantity = parseQuantity(dom.quantityInput.value);
  setFieldError(
    dom.quantityInput,
    dom.quantityError,
    quantity === null ? MESSAGES.QUANTITY_RANGE(state.limits.min_quantity, state.limits.max_quantity) : "",
  );

  const firstInvalid = [
    [setCode, dom.setInput],
    [number, dom.numberInput],
    [quantity, dom.quantityInput],
  ].find(([value]) => value === null);
  if (firstInvalid) {
    firstInvalid[1].focus();
    return null;
  }
  return { setCode, number, quantity };
}

// --- Entries -----------------------------------------------------------------

function addEntry(event) {
  event.preventDefault();
  const card = validateForm();
  if (!card) {
    return;
  }

  const key = entryKey(card.setCode, card.number);
  const existing = state.entries.find((entry) => entry.key === key);

  if (totalCards() + card.quantity > state.limits.max_total_cards) {
    setFieldError(dom.quantityInput, dom.quantityError, MESSAGES.TOTAL_CAP(state.limits.max_total_cards));
    dom.quantityInput.focus();
    return;
  }
  if (existing) {
    if (existing.quantity + card.quantity > state.limits.max_quantity) {
      setFieldError(dom.quantityInput, dom.quantityError, MESSAGES.CARD_QUANTITY_CAP(state.limits.max_quantity));
      dom.quantityInput.focus();
      return;
    }
    existing.quantity += card.quantity;
  } else {
    if (state.entries.length >= state.limits.max_entries) {
      setFieldError(dom.numberInput, dom.numberError, MESSAGES.ENTRY_CAP(state.limits.max_entries));
      dom.numberInput.focus();
      return;
    }
    state.entries.push({ key, ...card });
  }

  // Keep the set so several cards from one set can be entered quickly.
  dom.numberInput.value = "";
  dom.quantityInput.value = String(state.limits.min_quantity);
  dom.numberInput.focus();
  renderList();
}

function removeEntry(key) {
  state.entries = state.entries.filter((entry) => entry.key !== key);
  renderList();
}

function clearEntries() {
  state.entries = [];
  renderList();
  dom.setInput.focus();
}

function updateEntryQuantity(entry, input, errorElement) {
  const quantity = parseQuantity(input.value);
  if (quantity === null) {
    errorElement.textContent = MESSAGES.QUANTITY_RANGE(state.limits.min_quantity, state.limits.max_quantity);
    input.value = String(entry.quantity);
    return;
  }
  if (totalCards() - entry.quantity + quantity > state.limits.max_total_cards) {
    errorElement.textContent = MESSAGES.TOTAL_CAP(state.limits.max_total_cards);
    input.value = String(entry.quantity);
    return;
  }
  errorElement.textContent = "";
  entry.quantity = quantity;
  updateSummary();
}

// --- Rendering ---------------------------------------------------------------

function renderList() {
  const rows = state.entries.map((entry) => {
    const row = dom.rowTemplate.content.firstElementChild.cloneNode(true);
    const input = row.querySelector(".card-row__qty-input");
    const errorElement = row.querySelector(".card-row__error");
    row.querySelector(".card-row__set").textContent = entry.setCode;
    row.querySelector(".card-row__number").textContent = entry.number;
    if (entry.name) {
      row.querySelector(".card-row__name").textContent = entry.name;
      row.querySelector(".card-row__id").title = MESSAGES.IMPORTED_CARD_LABEL(entry.setCode, entry.number, entry.name);
    }
    input.min = String(state.limits.min_quantity);
    input.max = String(state.limits.max_quantity);
    input.value = String(entry.quantity);
    input.addEventListener("change", () => updateEntryQuantity(entry, input, errorElement));
    row.querySelector(".card-row__remove").addEventListener("click", () => removeEntry(entry.key));
    return row;
  });
  dom.list.replaceChildren(...rows);
  updateSummary();
}

function updateSummary() {
  const cards = totalCards();
  const overLimit = cards > state.limits.max_total_cards;
  const busy = state.controller !== null;

  const pages = pageCountFor(cards);
  dom.summaryCards.textContent = String(cards);
  dom.summaryCardsUnit.textContent = MESSAGES.CARD_UNIT(cards);
  dom.summaryPages.textContent = String(pages);
  dom.summaryPagesUnit.textContent = MESSAGES.PAGE_UNIT(pages);
  dom.emptyList.hidden = state.entries.length > 0;
  dom.clearButton.disabled = state.entries.length === 0 || busy;
  dom.importOpenButton.disabled = busy;
  dom.limitWarning.hidden = !overLimit;
  dom.limitWarning.textContent = overLimit ? MESSAGES.OVER_LIMIT(cards, state.limits.max_total_cards) : "";
  dom.generateButton.disabled = state.entries.length === 0 || overLimit || busy;
}

// --- Errors ------------------------------------------------------------------

function showErrors(title, details = [], requestId = null) {
  dom.errorTitle.textContent = title;
  const items = details.map((detail) => {
    const item = dom.errorItemTemplate.content.firstElementChild.cloneNode(true);
    item.textContent = detail;
    return item;
  });
  dom.errorList.replaceChildren(...items);
  dom.errorRequestId.hidden = !requestId;
  dom.errorRequestId.textContent = requestId ? MESSAGES.REQUEST_ID(requestId) : "";
  dom.errorPanel.hidden = false;
  console.error(title, { details, requestId });
}

function hideErrors() {
  dom.errorPanel.hidden = true;
  dom.errorList.replaceChildren();
}

// --- Generate ----------------------------------------------------------------

function setBusy(busy) {
  dom.formFields.disabled = busy;
  dom.cancelButton.hidden = !busy;
  dom.progress.hidden = !busy;
  if (busy) {
    dom.progressText.textContent = MESSAGES.WORKING(estimateSeconds());
  }
  updateSummary();
  dom.list.querySelectorAll("input, button").forEach((element) => {
    element.disabled = busy;
  });
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (error) {
    console.error("Response was not valid JSON", error);
    return undefined;
  }
}

// An operation is one in-flight request that can be cancelled or time out.
function startOperation(timeoutSeconds) {
  const operation = { controller: new AbortController(), abortReason: null, timeoutId: null };
  operation.timeoutId = window.setTimeout(
    () => abortOperation(operation, CONFIG.ABORT_REASON_TIMEOUT),
    timeoutSeconds * CONFIG.MS_PER_SECOND,
  );
  return operation;
}

function abortOperation(operation, reason) {
  if (operation && !operation.controller.signal.aborted) {
    operation.abortReason = reason;
    operation.controller.abort();
  }
}

function finishOperation(operation) {
  window.clearTimeout(operation.timeoutId);
}

function failure(title, details = [], requestId = null) {
  return { ok: false, cancelled: false, title, details, requestId };
}

/** POST JSON and classify every outcome: success, cancel, timeout, network, HTTP error, or unreadable body. */
async function postJson(route, body, operation) {
  let response;
  try {
    response = await fetch(route, {
      method: CONFIG.POST_METHOD,
      headers: {
        [CONFIG.CONTENT_TYPE_HEADER]: CONFIG.JSON_CONTENT_TYPE,
        [CONFIG.ACCEPT_HEADER]: CONFIG.JSON_CONTENT_TYPE,
      },
      body: JSON.stringify(body),
      signal: operation.controller.signal,
    });
  } catch (error) {
    if (error.name === CONFIG.ABORT_ERROR_NAME) {
      if (operation.abortReason === CONFIG.ABORT_REASON_TIMEOUT) {
        return failure(MESSAGES.TIMEOUT_TITLE, [MESSAGES.TIMEOUT_DETAIL]);
      }
      return { ...failure(MESSAGES.CANCELLED_TITLE), cancelled: true };
    }
    console.error(`Request to ${route} failed`, error);
    return failure(MESSAGES.NETWORK_TITLE, [MESSAGES.NETWORK_DETAIL]);
  }

  const headerRequestId = response.headers.get(CONFIG.REQUEST_ID_HEADER);
  const data = await readJson(response);
  const requestId = data?.request_id ?? headerRequestId;
  if (data === undefined) {
    return failure(response.ok ? MESSAGES.BAD_JSON_TITLE : MESSAGES.HTTP_TITLE(response.status), [], requestId);
  }
  if (!response.ok) {
    const details = Array.isArray(data.details) ? data.details : [];
    const title = typeof data.message === "string" ? data.message : MESSAGES.HTTP_TITLE(response.status);
    return failure(title, details, requestId);
  }
  return { ok: true, data, requestId };
}

async function generateSheet() {
  hideErrors();
  const operation = startOperation(estimateSeconds() + CONFIG.TIMEOUT_BUFFER_SECONDS);
  state.controller = operation;
  setBusy(true);
  const body = {
    cards: state.entries.map((entry) => ({ set_code: entry.setCode, number: entry.number, quantity: entry.quantity })),
  };

  try {
    const result = await postJson(API_ROUTES.SHEET, body, operation);
    if (!result.ok) {
      showErrors(result.title, result.details, result.requestId);
      return;
    }
    handleSheet(result.data, result.requestId);
  } finally {
    finishOperation(operation);
    state.controller = null;
    setBusy(false);
  }
}

function handleSheet(data, requestId) {
  if (!Array.isArray(data.pages) || !Array.isArray(data.errors)) {
    showErrors(MESSAGES.BAD_JSON_TITLE, [], requestId);
    return;
  }
  showPages(data.pages);
  if (data.errors.length > 0) {
    const title = data.pages.length === 0 ? MESSAGES.ALL_FAILED_TITLE : MESSAGES.PARTIAL_TITLE(data.errors.length);
    showErrors(title, data.errors.map(MESSAGES.CARD_ERROR), requestId);
  }
}

// --- Import ------------------------------------------------------------------

function countNonBlankLines(text) {
  return text.split(CONFIG.LINE_BREAK_PATTERN).filter((line) => line.trim()).length;
}

function estimateImportSeconds(lineCount) {
  return Math.ceil(lineCount * (state.limits.request_delay_seconds + CONFIG.ESTIMATED_NETWORK_SECONDS_PER_SEARCH));
}

function importTimeoutSeconds(lineCount) {
  const perLine =
    CONFIG.MAX_SEARCHES_PER_IMPORT_LINE *
    (state.limits.request_delay_seconds + CONFIG.ESTIMATED_NETWORK_SECONDS_PER_SEARCH);
  return Math.ceil(lineCount * perLine) + CONFIG.TIMEOUT_BUFFER_SECONDS;
}

function setImportBusy(busy) {
  dom.importText.readOnly = busy;
  dom.importSubmitButton.disabled = busy;
  dom.importProgress.hidden = !busy;
}

function clearImportIssues() {
  dom.importIssues.hidden = true;
  dom.importIssueList.replaceChildren();
  dom.importRequestId.hidden = true;
}

function showImportIssues(title, details, requestId = null) {
  dom.importIssuesTitle.textContent = title;
  const items = details.map((detail) => {
    const item = dom.errorItemTemplate.content.firstElementChild.cloneNode(true);
    item.textContent = detail;
    return item;
  });
  dom.importIssueList.replaceChildren(...items);
  dom.importRequestId.hidden = !requestId;
  dom.importRequestId.textContent = requestId ? MESSAGES.REQUEST_ID(requestId) : "";
  dom.importIssues.hidden = false;
  console.warn(title, { details, requestId });
}

function openImportDialog() {
  setFieldError(dom.importText, dom.importTextError, "");
  clearImportIssues();
  dom.importDialog.showModal();
  dom.importText.focus();
}

function closeImportDialog() {
  abortOperation(state.importOperation, CONFIG.ABORT_REASON_CANCEL);
  if (dom.importDialog.open) {
    dom.importDialog.close();
  }
}

function validateImportText() {
  const text = dom.importText.value;
  const lineCount = countNonBlankLines(text);
  let message = "";
  if (lineCount === 0) {
    message = MESSAGES.IMPORT_EMPTY;
  } else if (text.length > state.limits.max_import_text_length) {
    message = MESSAGES.IMPORT_TOO_LONG(state.limits.max_import_text_length);
  } else if (lineCount > state.limits.max_import_lines) {
    message = MESSAGES.IMPORT_TOO_MANY_LINES(lineCount, state.limits.max_import_lines);
  }
  setFieldError(dom.importText, dom.importTextError, message);
  return message ? null : { text, lineCount };
}

/** Add imported cards to the list, honoring the same limits as manual entry. Returns skip messages. */
function mergeImportedCards(cards) {
  const skipped = [];
  let copies = 0;
  let added = 0;
  for (const card of cards) {
    const setCode = normalizeIdentifier(String(card.set_code));
    const number = normalizeIdentifier(String(card.number));
    const quantity = Number(card.quantity);
    const label = MESSAGES.IMPORTED_CARD_LABEL(setCode, number, card.name);
    const key = entryKey(setCode, number);
    const existing = state.entries.find((entry) => entry.key === key);
    const currentQuantity = existing ? existing.quantity : 0;

    let reason = null;
    if (!existing && state.entries.length >= state.limits.max_entries) {
      reason = MESSAGES.ENTRY_CAP(state.limits.max_entries);
    } else if (currentQuantity + quantity > state.limits.max_quantity) {
      reason = MESSAGES.CARD_QUANTITY_CAP(state.limits.max_quantity);
    } else if (totalCards() + quantity > state.limits.max_total_cards) {
      reason = MESSAGES.TOTAL_CAP(state.limits.max_total_cards);
    }
    if (reason) {
      skipped.push(MESSAGES.IMPORT_SKIPPED(label, reason));
      continue;
    }

    if (existing) {
      existing.quantity += quantity;
      existing.name = existing.name || card.name;
    } else {
      state.entries.push({ key, setCode, number, quantity, name: card.name });
    }
    added += 1;
    copies += quantity;
  }
  renderList();
  return { added, copies, skipped };
}

function showImportStatus(added, copies) {
  dom.importStatus.hidden = added === 0;
  dom.importStatus.textContent = added > 0 ? MESSAGES.IMPORT_DONE(added, copies) : "";
}

async function submitImport(event) {
  event.preventDefault();
  if (state.importOperation) {
    return;
  }
  const input = validateImportText();
  if (!input) {
    dom.importText.focus();
    return;
  }

  clearImportIssues();
  const operation = startOperation(importTimeoutSeconds(input.lineCount));
  state.importOperation = operation;
  dom.importProgressText.textContent = MESSAGES.IMPORT_WORKING(estimateImportSeconds(input.lineCount));
  setImportBusy(true);

  try {
    const result = await postJson(API_ROUTES.IMPORT, { text: input.text }, operation);
    if (result.cancelled) {
      return;
    }
    if (!result.ok) {
      showImportIssues(result.title, result.details, result.requestId);
      return;
    }
    handleImport(result.data, result.requestId);
  } finally {
    finishOperation(operation);
    state.importOperation = null;
    setImportBusy(false);
  }
}

function handleImport(data, requestId) {
  if (!Array.isArray(data.cards) || !Array.isArray(data.issues)) {
    showImportIssues(MESSAGES.BAD_JSON_TITLE, [], requestId);
    return;
  }
  const { added, copies, skipped } = mergeImportedCards(data.cards);
  showImportStatus(added, copies);

  const details = [...data.issues.map(MESSAGES.IMPORT_ISSUE), ...skipped];
  if (details.length === 0) {
    closeImportDialog();
    return;
  }
  // Leave only the lines that failed so they can be fixed and imported again.
  dom.importText.value = data.issues.map((issue) => issue.line).join(CONFIG.LINE_BREAK);
  const title = added > 0 ? MESSAGES.IMPORT_PARTIAL_TITLE(added, details.length) : MESSAGES.IMPORT_FAILED_TITLE;
  showImportIssues(title, details, requestId);
}

// --- Viewer and print --------------------------------------------------------

function showPages(pages) {
  state.pages = pages.map((page) => CONFIG.JPEG_DATA_URL_PREFIX + page);
  state.pageIndex = CONFIG.FIRST_PAGE_INDEX;

  const printImages = state.pages.map((src) => {
    const image = document.createElement("img");
    image.className = "print-root__page";
    image.alt = "";
    image.src = src;
    return image;
  });
  dom.printRoot.replaceChildren(...printImages);

  const hasPages = state.pages.length > 0;
  dom.viewer.hidden = !hasPages;
  dom.viewerEmpty.hidden = hasPages;
  dom.printButton.hidden = !hasPages;
  if (hasPages) {
    renderPage();
  }
}

function renderPage() {
  const total = state.pages.length;
  const current = state.pageIndex + 1;
  dom.viewerImage.src = state.pages[state.pageIndex];
  dom.viewerImage.alt = MESSAGES.PAGE_ALT(current, total);
  dom.pageCounter.textContent = MESSAGES.PAGE_COUNTER(current, total);
  dom.prevPage.disabled = state.pageIndex === CONFIG.FIRST_PAGE_INDEX;
  dom.nextPage.disabled = current >= total;
}

function changePage(step) {
  const next = state.pageIndex + step;
  if (next >= CONFIG.FIRST_PAGE_INDEX && next < state.pages.length) {
    state.pageIndex = next;
    renderPage();
  }
}

async function printSheet() {
  const images = Array.from(dom.printRoot.querySelectorAll("img"));
  try {
    await Promise.all(images.map((image) => image.decode()));
  } catch (error) {
    console.error("Page images failed to decode", error);
    showErrors(MESSAGES.PRINT_FAILED_TITLE);
    return;
  }
  window.print();
}

// --- Startup -----------------------------------------------------------------

async function loadLimits() {
  const response = await fetch(API_ROUTES.CONFIG, { headers: { [CONFIG.ACCEPT_HEADER]: CONFIG.JSON_CONTENT_TYPE } });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

function applyLimits(limits) {
  state.limits = Object.freeze(limits);
  dom.setInput.maxLength = limits.max_identifier_length;
  dom.numberInput.maxLength = limits.max_identifier_length;
  dom.quantityInput.min = String(limits.min_quantity);
  dom.quantityInput.max = String(limits.max_quantity);
  dom.quantityInput.value = String(limits.min_quantity);
  dom.formFields.disabled = false;
  renderList();
}

function bindEvents() {
  dom.form.addEventListener("submit", addEntry);
  dom.clearButton.addEventListener("click", clearEntries);
  dom.generateButton.addEventListener("click", generateSheet);
  dom.cancelButton.addEventListener("click", () => abortOperation(state.controller, CONFIG.ABORT_REASON_CANCEL));
  dom.importOpenButton.addEventListener("click", openImportDialog);
  dom.importForm.addEventListener("submit", submitImport);
  dom.importCancelButton.addEventListener("click", closeImportDialog);
  // Escape fires "cancel"; any way the dialog closes must also stop an in-flight lookup.
  dom.importDialog.addEventListener("cancel", () => abortOperation(state.importOperation, CONFIG.ABORT_REASON_CANCEL));
  dom.importDialog.addEventListener("close", () => abortOperation(state.importOperation, CONFIG.ABORT_REASON_CANCEL));
  dom.errorDismiss.addEventListener("click", hideErrors);
  dom.prevPage.addEventListener("click", () => changePage(-1));
  dom.nextPage.addEventListener("click", () => changePage(1));
  dom.printButton.addEventListener("click", printSheet);
}

async function init() {
  bindEvents();
  try {
    applyLimits(await loadLimits());
    dom.setInput.focus();
  } catch (error) {
    console.error("Could not load server limits", error);
    showErrors(MESSAGES.CONFIG_FAILED);
  }
}

init();
