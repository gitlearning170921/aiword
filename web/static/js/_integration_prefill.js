/**
 * 审核 / 审核后修改 / 翻译页：与初稿页一致的页面2预填 + aicheckword bootstrap 下拉。
 */
(function (global) {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  function parsePrefillFromLocation() {
    try {
      var q = new URLSearchParams(window.location.search || "");
      if (
        !q.get("from") &&
        !q.get("upload_id") &&
        !q.get("upload_ids") &&
        !q.get("aicheckword_project_id") &&
        !q.get("project_id") &&
        !q.get("project_name")
      ) {
        return null;
      }
      var apid = (q.get("aicheckword_project_id") || "").trim();
      if (!apid && q.get("project_id")) {
        var p0 = String(q.get("project_id")).trim();
        if (/^\d+$/.test(p0)) apid = p0;
      }
      var bcRaw = (q.get("base_case_id") || q.get("base_case") || "").trim();
      var bcn = parseInt(bcRaw, 10);
      return {
        fromPage2: q.get("from") === "page2" || !!q.get("upload_id"),
        upload_id: (q.get("upload_id") || "").trim(),
        upload_ids: (q.get("upload_ids") || "").trim(),
        project_name: (q.get("project_name") || "").trim(),
        file_name: (q.get("file_name") || "").trim(),
        product: (q.get("product") || q.get("registered_product") || "").trim(),
        country: (q.get("country") || "").trim(),
        collection: (q.get("collection") || "").trim(),
        base_case_id: isNaN(bcn) || bcn <= 0 ? null : bcn,
        aicheckword_project_id: (function () {
          if (!apid) return null;
          var n = parseInt(apid, 10);
          return isNaN(n) || n <= 0 ? null : n;
        })(),
      };
    } catch (_) {
      return null;
    }
  }

  function _normCountryKey(s) {
    return String(s || "").trim().toLowerCase().replace(/\s+/g, " ");
  }

  function classifyRegRouteFromCountry(countryRaw) {
    var s = _normCountryKey(countryRaw);
    if (!s) return "default";
    if (s.indexOf("中国") >= 0 || s.indexOf("药监局") >= 0 || s.indexOf("境内") >= 0) return "nmpa";
    if (s === "cn" || s.indexOf("nmpa") >= 0) return "nmpa";
    if (
      s === "us" || s === "usa" || s.indexOf("united states") >= 0 ||
      s.indexOf("u.s.") >= 0 || s.indexOf("america") >= 0 || s === "fda" || s.indexOf("fda") >= 0
    ) return "fda";
    if (s.indexOf("美国") >= 0) return "fda";
    if (
      s === "eu" || s.indexOf("european union") >= 0 || s.indexOf("europe") >= 0 ||
      /\bce\b/.test(s) || s.indexOf("eea") >= 0
    ) return "ce";
    if (s.indexOf("欧盟") >= 0 || s.indexOf("欧洲") >= 0) return "ce";
    return "default";
  }

  function _countryMatchAgainstAicheckwordEn(aiwordCountry, registrationCountryEn) {
    var ac = _normCountryKey(aiwordCountry);
    if (!ac) return false;
    var en = _normCountryKey(registrationCountryEn);
    if (!en) return false;
    if (en === ac) return true;
    if (en.indexOf(ac) >= 0 || ac.indexOf(en) >= 0) return true;
    return false;
  }

  function _scoreNamePair(needle, field) {
    var a = String(needle || "").trim();
    var b = String(field || "").trim();
    if (!a || !b) return 0;
    if (a === b) return 1000;
    if (b.indexOf(a) >= 0 || a.indexOf(b) >= 0) return 600;
    var as = a.replace(/\s+/g, "");
    var bs = b.replace(/\s+/g, "");
    if (as && bs && (bs.indexOf(as) >= 0 || as.indexOf(bs) >= 0)) return 350;
    var al = a.toLowerCase();
    var bl = b.toLowerCase();
    if (al === bl) return 300;
    if (bl.indexOf(al) >= 0 || al.indexOf(bl) >= 0) return 150;
    return 0;
  }

  function scoreProjectForPage2Prefill(p, pf, route) {
    var needle = String(pf.project_name || "").trim();
    var sc = 0;
    if (needle) {
      if (route === "nmpa") {
        sc = _scoreNamePair(needle, p.productName);
      } else if (route === "fda" || route === "ce") {
        sc = _scoreNamePair(needle, p.productNameEn);
        if (!sc) sc = Math.floor(_scoreNamePair(needle, p.productName) * 0.45);
      } else {
        sc = Math.max(
          _scoreNamePair(needle, p.productName),
          Math.floor(_scoreNamePair(needle, p.productNameEn) * 0.92)
        );
      }
      var nm = String(p.name || "").trim();
      if (nm && (nm.indexOf(needle) >= 0 || needle.indexOf(nm) >= 0)) sc += 35;
    }
    var aux = String(pf.product || "").trim();
    if (aux) {
      sc += Math.max(
        _scoreNamePair(aux, p.productName),
        Math.floor(_scoreNamePair(aux, p.productNameEn) * 0.85)
      );
    }
    if (_countryMatchAgainstAicheckwordEn(pf.country, p.registrationCountryEn)) sc += 40;
    return sc;
  }

  function scoreCaseForPage2Prefill(c, pf, route) {
    var needle = String(pf.project_name || "").trim();
    if (!needle) return 0;
    var sc = 0;
    if (route === "nmpa") {
      sc = _scoreNamePair(needle, c.productName);
    } else if (route === "fda" || route === "ce") {
      sc = _scoreNamePair(needle, c.productNameEn);
      if (!sc) sc = Math.floor(_scoreNamePair(needle, c.productName) * 0.45);
    } else {
      sc = Math.max(
        _scoreNamePair(needle, c.productName),
        Math.floor(_scoreNamePair(needle, c.productNameEn) * 0.92)
      );
    }
    var aux = String(pf.product || "").trim();
    if (aux) {
      sc += Math.max(
        _scoreNamePair(aux, c.productName),
        Math.floor(_scoreNamePair(aux, c.productNameEn) * 0.85)
      );
    }
    if (_countryMatchAgainstAicheckwordEn(pf.country, c.registrationCountryEn)) sc += 80;
    return sc;
  }

  var PROJECT_EMPTY_OPT = { value: "", label: "请选择 aicheckword 项目（必选）" };
  var PROJECT_SELECT_CACHE = {};

  function projectSelectId(prefix) {
    return prefix + "_project_sel";
  }

  function projectFilterId(prefix) {
    return prefix + "_project_sel_filter";
  }

  function pagePrefillKey(prefix) {
    return "__integrationPagePrefill_" + prefix;
  }

  function storePagePrefill(prefix, pf) {
    if (pf) global[pagePrefillKey(prefix)] = pf;
  }

  function getPagePrefill(prefix) {
    return global[pagePrefillKey(prefix)] || null;
  }

  function setProjectPrefillBadge(prefix, visible) {
    var tag = $(prefix + "_pf_project");
    if (!tag) return;
    if (visible) tag.classList.remove("d-none");
    else tag.classList.add("d-none");
  }

  function rememberProjectSelectRows(prefix, rows) {
    PROJECT_SELECT_CACHE[projectSelectId(prefix)] = {
      rows: rows || [],
      valueKey: "id",
      labelKey: "label",
      emptyOpt: PROJECT_EMPTY_OPT,
    };
  }

  function applyProjectSelectFilter(prefix) {
    var selId = projectSelectId(prefix);
    var cache = PROJECT_SELECT_CACHE[selId];
    var sel = $(selId);
    if (!cache || !sel) return;
    var fin = $(projectFilterId(prefix));
    var needle = (fin && fin.value) ? fin.value.trim().toLowerCase() : "";
    var cur = (sel.value || "").trim();
    var rows = cache.rows;
    if (needle) {
      rows = cache.rows.filter(function (r) {
        var v = String(r[cache.valueKey] != null ? r[cache.valueKey] : "").toLowerCase();
        var lab = String(r[cache.labelKey] != null ? r[cache.labelKey] : v).toLowerCase();
        return v.indexOf(needle) >= 0 || lab.indexOf(needle) >= 0;
      });
    }
    fillSelect(selId, rows, cache.valueKey, cache.labelKey, cache.emptyOpt);
    var vals = Array.prototype.map.call(sel.options, function (o) { return String(o.value); });
    if (cur && vals.indexOf(cur) < 0) {
      var opt = document.createElement("option");
      opt.value = cur;
      opt.textContent = "【已选】ID:" + cur;
      sel.appendChild(opt);
      sel.value = cur;
    } else if (cur && vals.indexOf(cur) >= 0) {
      sel.value = cur;
    }
    var hid = $(prefix + "_project_id");
    if (hid) hid.value = sel.value || "";
  }

  function wireProjectFilter(prefix) {
    var fin = $(projectFilterId(prefix));
    if (!fin || fin._integrationFilterBound) return;
    fin._integrationFilterBound = true;
    fin.addEventListener("input", function () {
      applyProjectSelectFilter(prefix);
    });
  }

  function getTaskUploadIdFromPage(prefix) {
    var idsEl = $(prefix + "_upload_ids");
    if (idsEl && String(idsEl.value || "").trim()) {
      return String(idsEl.value || "")
        .split(/[\n,]+/)
        .map(function (s) { return s.trim(); })
        .filter(Boolean)[0] || "";
    }
    var one = $(prefix + "_upload_id");
    if (one && String(one.value || "").trim()) return String(one.value || "").trim();
    var base = $(prefix + "_base_upload_id");
    if (base && String(base.value || "").trim()) return String(base.value || "").trim();
    return "";
  }

  function mergeUploadPrefillFields(pf, d) {
    var out = {};
    Object.keys(pf || {}).forEach(function (k) { out[k] = pf[k]; });
    if (!out.project_name && d.project_name) out.project_name = d.project_name;
    if (!out.file_name && d.file_name) out.file_name = d.file_name;
    if (!out.product && d.product) out.product = d.product;
    if (!out.country && d.country) out.country = d.country;
    if (!out.upload_id && d.uploadId) out.upload_id = d.uploadId;
    out.fromPage2 = out.fromPage2 || !!d.fromPage2;
    var apid = d.aicheckwordProjectId != null ? d.aicheckwordProjectId : d.aicheckword_project_id;
    if (apid != null && apid !== "") {
      var n = parseInt(String(apid), 10);
      if (!isNaN(n) && n > 0) out.aicheckword_project_id = n;
    }
    return out;
  }

  function rematchProjectFromTask(prefix, opts) {
    opts = opts || {};
    var b = global["__integrationBootstrap_" + prefix];
    if (!b) return Promise.resolve(null);
    var uploadBase = opts.uploadPrefillBase || opts.root + "/audit";
    var pf0 = getPagePrefill(prefix) || parsePrefillFromLocation() || {};
    var uid = getTaskUploadIdFromPage(prefix);
    if (!uid) {
      if (!opts.silent) setProjectPrefillBadge(prefix, false);
      return Promise.resolve(pf0);
    }
    pf0 = Object.assign({}, pf0, { upload_id: uid, fromPage2: true });
    return enrichPrefillFromUpload(opts.root || "", pf0, uploadBase).then(function (pf) {
      storePagePrefill(prefix, pf);
      applyPage2Prefill(prefix, b, pf, opts);
      return pf;
    });
  }

  function requireAicheckwordProject(prefix) {
    var sel = $(projectSelectId(prefix));
    var pid = (sel && sel.value) || ($(prefix + "_project_id") && $(prefix + "_project_id").value) || "";
    pid = String(pid || "").trim();
    var n = parseInt(pid, 10);
    if (!pid || isNaN(n) || n <= 0) {
      return { ok: false, message: "请从下拉列表选择 aicheckword 项目（数据来自 aicheckword，与 Streamlit 按项目审核一致）" };
    }
    return { ok: true, projectId: n };
  }

  function fillSelect(selId, rows, valueKey, labelKey, emptyOpt) {
    var sel = $(selId);
    if (!sel) return;
    var old = String(sel.value || "");
    sel.innerHTML = "";
    if (emptyOpt) {
      var o0 = document.createElement("option");
      o0.value = emptyOpt.value != null ? String(emptyOpt.value) : "";
      o0.textContent = emptyOpt.label || "不指定";
      sel.appendChild(o0);
    }
    (rows || []).forEach(function (row) {
      if (!row) return;
      var op = document.createElement("option");
      op.value = String(row[valueKey] != null ? row[valueKey] : "");
      op.textContent = String(row[labelKey] != null ? row[labelKey] : op.value);
      sel.appendChild(op);
    });
    if (old) {
      var vals = Array.prototype.map.call(sel.options, function (o) { return String(o.value); });
      if (vals.indexOf(old) >= 0) sel.value = old;
    }
  }

  function setSelectValue(selId, val) {
    var sel = $(selId);
    if (!sel || val == null || val === "") return false;
    var want = String(val);
    var vals = Array.prototype.map.call(sel.options, function (o) { return String(o.value); });
    if (vals.indexOf(want) >= 0) {
      sel.value = want;
      return true;
    }
    return false;
  }

  function pickBestProjectId(projects, pf) {
    if (!pf || !projects || !projects.length) return null;
    if (pf.aicheckword_project_id) {
      var want = String(pf.aicheckword_project_id);
      for (var i = 0; i < projects.length; i++) {
        if (String(projects[i].id) === want) return want;
      }
    }
    var route = classifyRegRouteFromCountry(pf.country);
    var bestId = null;
    var bestSc = 0;
    projects.forEach(function (p) {
      var sc = scoreProjectForPage2Prefill(p, pf, route);
      if (sc > bestSc) {
        bestSc = sc;
        bestId = p.id;
      }
    });
    if (bestSc >= 80 && bestId != null) return String(bestId);
    var pn = (pf.project_name || "").trim().toLowerCase();
    if (pn) {
      for (var j = 0; j < projects.length; j++) {
        var lab = String(projects[j].label || projects[j].name || "").toLowerCase();
        if (lab.indexOf(pn) >= 0 || pn.indexOf(lab) >= 0) return String(projects[j].id);
      }
    }
    return null;
  }

  function pickBestCaseId(cases, pf) {
    if (!pf || !cases || !cases.length) return null;
    var route = classifyRegRouteFromCountry(pf.country);
    var bestId = null;
    var bestSc = 0;
    cases.forEach(function (c) {
      var sc = scoreCaseForPage2Prefill(c, pf, route);
      if (sc > bestSc) {
        bestSc = sc;
        bestId = c.id;
      }
    });
    return bestSc >= 80 && bestId != null ? String(bestId) : null;
  }

  function findProjectRow(projects, pid) {
    var id = String(pid || "");
    if (!id) return null;
    for (var i = 0; i < (projects || []).length; i++) {
      if (String(projects[i].id) === id) return projects[i];
    }
    return null;
  }

  function _setCountrySelect(prefix, proj, pf) {
    var csel = $(prefix + "_registration_country");
    if (!csel) return;
    var vals = [
      proj.registrationCountry,
      proj.registrationCountryEn,
      pf && pf.country,
    ];
    for (var i = 0; i < vals.length; i++) {
      var v = String(vals[i] || "").trim();
      if (!v) continue;
      if (setSelectValue(prefix + "_registration_country", v)) return;
      var matched = false;
      Array.prototype.forEach.call(csel.options, function (o) {
        if (matched) return;
        var t = (o.textContent || "") + " " + o.value;
        if (t.indexOf(v) >= 0 || v.indexOf(o.value) >= 0) {
          csel.value = o.value;
          matched = true;
        }
      });
      if (matched) return;
    }
  }

  function applyProjectDimensions(prefix, proj, pf) {
    if (!proj) return;
    _setCountrySelect(prefix, proj, pf || {});
    var map = {
      registration_type: proj.registrationType,
      registration_component: proj.registrationComponent,
      project_form: proj.projectForm,
      document_language: proj.documentLanguage || "",
    };
    Object.keys(map).forEach(function (k) {
      if (map[k]) setSelectValue(prefix + "_" + k, map[k]);
    });
  }

  function applyCaseDimensions(prefix, c, pf) {
    if (!c) return;
    _setCountrySelect(prefix, c, pf || {});
    var map = {
      registration_type: c.registrationType,
      project_form: c.projectForm,
      document_language: c.documentLanguage || "",
    };
    Object.keys(map).forEach(function (k) {
      if (map[k]) setSelectValue(prefix + "_" + k, map[k]);
    });
  }

  var pfCountryRoute = "";

  function wireProjectSelect(prefix, bootstrapGetter, pfGetter) {
    var sel = $(prefix + "_project_sel");
    if (!sel) return;
    sel.addEventListener("change", function () {
      var pid = String(sel.value || "").trim();
      var hid = $(prefix + "_project_id");
      if (hid) hid.value = pid;
      var b = bootstrapGetter();
      var pf = pfGetter ? pfGetter() : null;
      applyProjectDimensions(prefix, findProjectRow(b && b.projects, pid), pf);
    });
  }

  function wireCaseSelect(prefix, bootstrapGetter, pfGetter) {
    var sel = $(prefix + "_base_case_id");
    if (!sel) return;
    sel.addEventListener("change", function () {
      var cid = String(sel.value || "").trim();
      if (!cid) return;
      var b = bootstrapGetter();
      var cases = (b && b.cases) || [];
      var row = null;
      for (var i = 0; i < cases.length; i++) {
        if (String(cases[i].id) === cid) {
          row = cases[i];
          break;
        }
      }
      applyCaseDimensions(prefix, row, pfGetter ? pfGetter() : null);
    });
  }

  function applyPage2Prefill(prefix, b, pf, opts) {
    opts = opts || {};
    if (!pf) return;
    pfCountryRoute = pf.country ? classifyRegRouteFromCountry(pf.country) : "";

    if (pf.collection && (b.organizations || []).length) {
      var matchedOrg = "";
      (b.organizations || []).forEach(function (o) {
        if (String(o.knowledgeCollection || "") === String(pf.collection)) matchedOrg = String(o.id || "");
      });
      if (matchedOrg && $(organizationSelectId(prefix))) {
        setSelectValue(organizationSelectId(prefix), matchedOrg);
        syncCollectionFromOrganization(prefix, matchedOrg, b.organizations);
      } else if (pf.collection && $(prefix + "_collection")) {
        setSelectValue(prefix + "_collection", pf.collection);
      }
    } else if (pf.collection && $(prefix + "_collection") && $(prefix + "_collection").tagName === "SELECT") {
      setSelectValue(prefix + "_collection", pf.collection);
    }

    var pid = pickBestProjectId(b.projects || [], pf);
    if (pid) {
      setSelectValue(prefix + "_project_sel", pid);
      var hid = $(prefix + "_project_id");
      if (hid) hid.value = pid;
      applyProjectDimensions(prefix, findProjectRow(b.projects, pid), pf);
      setProjectPrefillBadge(prefix, true);
    } else {
      setProjectPrefillBadge(prefix, false);
    }

    var caseEl = $(prefix + "_base_case_id");
    if (caseEl) {
      var targetBc = null;
      if (opts.baseCaseId) targetBc = String(opts.baseCaseId);
      else if (pf.base_case_id) targetBc = String(pf.base_case_id);
      if (!targetBc) targetBc = pickBestCaseId(b.cases || [], pf);
      if (targetBc) {
        setSelectValue(prefix + "_base_case_id", targetBc);
        var cases = b.cases || [];
        for (var ci = 0; ci < cases.length; ci++) {
          if (String(cases[ci].id) === targetBc) {
            applyCaseDimensions(prefix, cases[ci], pf);
            break;
          }
        }
      }
    }

    if (!pid && pf.country) {
      var csel0 = $(prefix + "_registration_country");
      if (csel0) {
        Array.prototype.forEach.call(csel0.options, function (o) {
          var t = (o.textContent || "") + " " + o.value;
          if (t.indexOf(pf.country) >= 0 || pf.country.indexOf(o.value) >= 0) {
            csel0.value = o.value;
          }
        });
      }
    }

    if (pfCountryRoute === "fda" || pfCountryRoute === "ce") {
      setSelectValue(prefix + "_document_language", "en");
    } else if (pfCountryRoute === "nmpa") {
      setSelectValue(prefix + "_document_language", "zh");
    }
  }

  function enrichPrefillFromUpload(root, pf, uploadPrefillBase) {
    if (!pf) pf = {};
    var uid = (pf.upload_id || "").trim();
    if (!uid && pf.upload_ids) {
      uid = String(pf.upload_ids).split(/[\n,]+/).map(function (s) { return s.trim(); }).filter(Boolean)[0] || "";
    }
    if (!uid || !global.AsyncJob) return Promise.resolve(pf);
    var base = String(uploadPrefillBase || root + "/audit").replace(/\/$/, "");
    return global.AsyncJob.api(
      base + "/api/upload-prefill?upload_id=" + encodeURIComponent(uid),
      { method: "GET" }
    ).then(function (x) {
      if (!x.ok || !x.json || !x.json.ok) return pf;
      return mergeUploadPrefillFields(pf, x.json);
    }).catch(function () { return pf; });
  }

  function organizationSelectId(prefix) {
    return prefix + "_organization";
  }

  function syncCollectionFromOrganization(prefix, orgId, orgs) {
    var collEl = $(prefix + "_collection");
    var dispEl = $(prefix + "_collection_display");
    var kc = "regulations";
    (orgs || []).forEach(function (o) {
      if (String(o.id || "") === String(orgId || "")) {
        kc = String(o.knowledgeCollection || "regulations").trim() || "regulations";
      }
    });
    if (collEl) collEl.value = kc;
    if (dispEl) dispEl.textContent = kc;
    return kc;
  }

  function fillOrganizationSelect(prefix, orgs, activeId) {
    var sel = $(organizationSelectId(prefix));
    if (!sel) return "";
    sel.innerHTML = "";
    (orgs || []).forEach(function (o) {
      var opt = document.createElement("option");
      opt.value = String(o.id || "");
      opt.textContent = o.label || o.name || o.id;
      sel.appendChild(opt);
    });
    var pick = String(activeId || "").trim();
    if (pick) sel.value = pick;
    else if (orgs && orgs[0]) sel.value = String(orgs[0].id || "");
    if ((orgs || []).length <= 1) {
      sel.disabled = true;
      sel.title = "当前账号仅绑定一家公司";
    } else {
      sel.disabled = false;
      sel.removeAttribute("title");
    }
    return syncCollectionFromOrganization(prefix, sel.value, orgs);
  }

  function readOrganizationId(prefix) {
    var sel = $(organizationSelectId(prefix));
    return sel ? String(sel.value || "").trim() : "";
  }

  function wireOrganizationSelect(prefix, opts) {
    opts = opts || {};
    var sel = $(organizationSelectId(prefix));
    if (!sel || sel.__orgWired) return;
    sel.__orgWired = true;
    var apiRoot = String(opts.orgContextRoot || (opts.root || "") + "/audit").replace(/\/+$/, "");
    sel.addEventListener("change", function () {
      var oid = String(sel.value || "").trim();
      var orgs = global["__integrationOrgs_" + prefix] || [];
      syncCollectionFromOrganization(prefix, oid, orgs);
      if (!oid) {
        if (opts.onOrganizationChange) opts.onOrganizationChange(oid);
        return;
      }
      var body = JSON.stringify({ organizationId: oid });
      var headers = { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" };
      var req;
      if (global.AsyncJob && global.AsyncJob.api) {
        req = global.AsyncJob.api(apiRoot + "/api/org-context/active", {
          method: "POST",
          headers: headers,
          body: body,
        });
      } else {
        req = fetch(apiRoot + "/api/org-context/active", {
          method: "POST",
          credentials: "same-origin",
          headers: headers,
          body: body,
        }).then(function (r) {
          return r.json().catch(function () { return {}; }).then(function (j) {
            if (!r.ok) throw j;
            return { ok: true, json: j };
          });
        });
      }
      Promise.resolve(req).then(function () {
        if (opts.onOrganizationChange) opts.onOrganizationChange(oid);
      }).catch(function () {
        if (opts.onOrganizationChange) opts.onOrganizationChange(oid);
      });
    });
  }

  function loadBootstrap(opts) {
    opts = opts || {};
    var prefix = opts.prefix || "aud";
    var apiPath = opts.bootstrapUrl || (opts.root + "/audit/api/integration-bootstrap");
    var pf0 = opts.prefill !== undefined ? opts.prefill : parsePrefillFromLocation();
    var cacheKey = "__integrationBootstrap_" + prefix;
    var uploadBase = opts.uploadPrefillBase || opts.root + "/audit";

    return enrichPrefillFromUpload(opts.root || "", pf0, uploadBase).then(function (pf) {
    storePagePrefill(prefix, pf);
    var orgId = readOrganizationId(prefix);
    var collEl = $(prefix + "_collection");
    var coll = (collEl && collEl.value) ? collEl.value.trim() : "";
    if (!coll && pf && pf.collection) coll = pf.collection;
    if (!coll) coll = "regulations";
    var qs = [];
    if (orgId) qs.push("organizationId=" + encodeURIComponent(orgId));
    if (coll) qs.push("collection=" + encodeURIComponent(coll));
    var bootUrl = apiPath + (qs.length ? "?" + qs.join("&") : "");

    return (global.AsyncJob ? global.AsyncJob.api(
      bootUrl,
      { method: "GET" }
    ) : Promise.resolve({ ok: false })).then(function (x) {
      if (!x.ok || !x.json || !x.json.ok) {
        if (opts.onError) opts.onError((x.json && x.json.message) || "加载选项失败");
        return null;
      }
      var b = x.json;
      global[cacheKey] = b;
      global["__integrationOrgs_" + prefix] = b.organizations || [];

      if ($(organizationSelectId(prefix))) {
        var pickOrg = orgId || b.activeOrganizationId;
        fillOrganizationSelect(prefix, b.organizations, pickOrg);
        wireOrganizationSelect(prefix, {
          root: opts.root || "",
          orgContextRoot: opts.orgContextRoot,
          onOrganizationChange: function () {
            loadBootstrap(Object.assign({}, opts, {
              prefill: getPagePrefill(prefix) || parsePrefillFromLocation(),
            }));
          },
        });
        coll = syncCollectionFromOrganization(
          prefix,
          readOrganizationId(prefix) || pickOrg,
          b.organizations
        );
      } else if (collEl && collEl.tagName === "SELECT") {
        fillSelect(prefix + "_collection", b.collections || [], "id", "label", null);
        if (coll) setSelectValue(prefix + "_collection", coll);
      } else if (collEl) {
        collEl.value = b.collection || b.activeKnowledgeCollection || coll;
        var disp = $(prefix + "_collection_display");
        if (disp) disp.textContent = collEl.value;
      }

      rememberProjectSelectRows(prefix, b.projects || []);
      fillSelect(projectSelectId(prefix), b.projects || [], "id", "label", PROJECT_EMPTY_OPT);
      wireProjectFilter(prefix);
      var pfin = $(projectFilterId(prefix));
      if (pfin) pfin.value = "";
      if (opts.withCases !== false && $(prefix + "_base_case_id")) {
        fillSelect(prefix + "_base_case_id", b.cases || [], "id", "label", { value: "", label: "不指定" });
      }
      fillSelect(prefix + "_document_language", b.documentLanguages || [], "value", "label", null);
      fillSelect(prefix + "_registration_country", b.registrationCountries || [], "value", "label", null);
      fillSelect(prefix + "_registration_type", b.registrationTypes || [], "value", "label", null);
      fillSelect(prefix + "_registration_component", b.registrationComponents || [], "value", "label", null);
      fillSelect(prefix + "_project_form", b.projectForms || [], "value", "label", null);

      if (opts.onBootstrap) opts.onBootstrap(b, pf);
      if (pf) applyPage2Prefill(prefix, b, pf, opts);
      if (opts.onReady) opts.onReady(b, pf);
      return b;
    });
    });
  }

  function parseManualRulesText(text) {
    var out = [];
    String(text || "").split(/\n+/).forEach(function (line) {
      var s = line.trim();
      if (!s || s.indexOf("|") < 0) return;
      var parts = s.split("|").map(function (p) { return p.trim(); });
      if (parts.length < 2) return;
      var wrong = parts[0];
      var right = parts[1];
      var source = parts[2] || "";
      if (!wrong || !right) return;
      out.push({ wrong: wrong, right: right, source_zh: source });
    });
    return out;
  }

  var COMPANY_FIELD_KEYS = [
    ["company_name", "company_name"],
    ["address", "address"],
    ["contact", "contact"],
    ["phone", "phone"],
    ["fax", "fax"],
    ["email", "email"],
  ];

  function applyCompanyConfig(prefix, cfg, onlyEmpty) {
    cfg = cfg || {};
    COMPANY_FIELD_KEYS.forEach(function (pair) {
      var el = $(prefix + "_" + pair[0]);
      if (!el) return;
      var v = String(cfg[pair[1]] || "");
      if (!v) return;
      if (onlyEmpty && String(el.value || "").trim()) return;
      el.value = v;
    });
  }

  function integrationScopeFromLocation() {
    try {
      var q = new URLSearchParams(window.location.search || "");
      var scope = (q.get("scope") || "").trim().toLowerCase();
      if (scope === "page0" || scope === "workflow") return scope;
      var manual = (q.get("manual") || "").trim().toLowerCase();
      if (manual === "1" || manual === "true" || manual === "yes" || manual === "on") return "page0";
    } catch (e) { /* ignore */ }
    return "workflow";
  }

  function integrationScopeQuery() {
    return "scope=" + encodeURIComponent(integrationScopeFromLocation());
  }

  function appendIntegrationScope(fd) {
    if (fd && fd.append) {
      fd.append("integration_scope", integrationScopeFromLocation());
    }
  }

  function readCompanyOverrides(prefix) {
    var out = {};
    COMPANY_FIELD_KEYS.forEach(function (pair) {
      var el = $(prefix + "_" + pair[0]);
      var v = el ? String(el.value || "").trim() : "";
      if (v) out[pair[1]] = v;
    });
    return Object.keys(out).length ? out : null;
  }

  function loadOrganizationContext(opts) {
    opts = opts || {};
    var prefix = opts.prefix || "exam";
    var root = String(opts.root || "").replace(/\/+$/, "");
    var apiRoot = String(opts.orgContextRoot || root + "/audit").replace(/\/+$/, "");
    var url = apiRoot + "/api/org-context";
    var req;
    if (global.AsyncJob && global.AsyncJob.api) {
      req = global.AsyncJob.api(url, { method: "GET" }).then(function (x) {
        return (x && x.json) ? x.json : x;
      });
    } else {
      req = fetch(url, { credentials: "same-origin" }).then(function (r) {
        return r.json();
      });
    }
    return Promise.resolve(req).then(function (data) {
      var orgs = (data && data.organizations) || [];
      global["__integrationOrgs_" + prefix] = orgs;
      if ($(organizationSelectId(prefix))) {
        fillOrganizationSelect(prefix, orgs, data && data.activeOrganizationId);
        wireOrganizationSelect(prefix, {
          orgContextRoot: apiRoot,
          onOrganizationChange: opts.onOrganizationChange,
        });
      }
      return data;
    }).catch(function () {
      var sel = $(organizationSelectId(prefix));
      if (sel) sel.innerHTML = '<option value="">公司列表加载失败</option>';
      return null;
    });
  }

  global.IntegrationPrefill = {
    $: $,
    parsePrefillFromLocation: parsePrefillFromLocation,
    fillSelect: fillSelect,
    setSelectValue: setSelectValue,
    pickBestProjectId: pickBestProjectId,
    pickBestCaseId: pickBestCaseId,
    findProjectRow: findProjectRow,
    applyProjectDimensions: applyProjectDimensions,
    applyCaseDimensions: applyCaseDimensions,
    wireProjectSelect: wireProjectSelect,
    wireProjectFilter: wireProjectFilter,
    wireCaseSelect: wireCaseSelect,
    enrichPrefillFromUpload: enrichPrefillFromUpload,
    applyPage2Prefill: applyPage2Prefill,
    loadBootstrap: loadBootstrap,
    rematchProjectFromTask: rematchProjectFromTask,
    getPagePrefill: getPagePrefill,
    storePagePrefill: storePagePrefill,
    getTaskUploadIdFromPage: getTaskUploadIdFromPage,
    requireAicheckwordProject: requireAicheckwordProject,
    setProjectPrefillBadge: setProjectPrefillBadge,
    parseManualRulesText: parseManualRulesText,
    applyCompanyConfig: applyCompanyConfig,
    readCompanyOverrides: readCompanyOverrides,
    readOrganizationId: readOrganizationId,
    syncCollectionFromOrganization: syncCollectionFromOrganization,
    fillOrganizationSelect: fillOrganizationSelect,
    wireOrganizationSelect: wireOrganizationSelect,
    loadOrganizationContext: loadOrganizationContext,
    integrationScopeFromLocation: integrationScopeFromLocation,
    integrationScopeQuery: integrationScopeQuery,
    appendIntegrationScope: appendIntegrationScope,
    classifyRegRouteFromCountry: classifyRegRouteFromCountry,
    PROJECT_EMPTY_OPT: PROJECT_EMPTY_OPT,
  };
})(window);
