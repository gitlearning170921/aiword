(function () {
  const root = (typeof window.__SCRIPT_ROOT__ === "string" ? window.__SCRIPT_ROOT__ : "") || "";
  let lastHasLlmKey = false;
  let lastPersonalKeysOnly = true;
  /** @type {Record<string, boolean>} */
  var lastHasApiKeyByProvider = { deepseek: false, cursor: false, tongyi: false };
  /** @type {Record<string, string>} */
  var lastApiBaseByProvider = { deepseek: "", cursor: "", tongyi: "" };
  /** @type {Record<string, string>} */
  var lastLlmModelByProvider = { deepseek: "", cursor: "", tongyi: "" };
  var lastLlmProviderSelection = "deepseek";
  /** @type {any} */
  let lastBootstrap = null;

  function dgIntegrationScopeFromLocation() {
    try {
      var q = new URLSearchParams(window.location.search || "");
      var scope = (q.get("scope") || "").trim().toLowerCase();
      if (scope === "page0" || scope === "workflow") return scope;
      var manual = (q.get("manual") || "").trim().toLowerCase();
      if (manual === "1" || manual === "true" || manual === "yes" || manual === "on") return "page0";
    } catch (e) { /* ignore */ }
    return "workflow";
  }

  function dgIntegrationScopeQuery() {
    return "scope=" + encodeURIComponent(dgIntegrationScopeFromLocation());
  }

  function dgIsSuperAdmin() {
    return !!window.__PAGE13_SUPER_ADMIN__;
  }

  function dgUserText(adminText, userText) {
    return typeof window.ufText === "function" ? window.ufText(adminText, userText) : (dgIsSuperAdmin() ? adminText : userText);
  }

  /** 与 aicheckword 初稿页 file_uploader type= 一致 */
  var DRAFT_UPLOAD_ACCEPT = ".docx,.doc,.pdf,.xlsx,.xls,.txt,.md,.zip,.tar,.gz,.tgz";
  /** @type {File[]} */
  var _dgInputFilesAccum = [];
  /** @type {File[]} */
  var _dgBaseFilesAccum = [];
  var _dgFilePickersWired = false;
  /** 页面2带入的任务 upload_id，提交时写入 payload.base_upload_id */
  var _dgBaseUploadId = "";
  /** 页面1 → aicheckword 新建后关联的项目 id */
  var _dgLinkedAcwProjectId = 0;
  /** @type {any[]} */
  var _dgPage1ProjectsCache = [];
  /** @type {any} */
  var _dgAcwMetaFields = null;
  var _dgAcwModalInstance = null;

  var __page2Prefill = null;
  var __page2PrefillApplied = false;
  var __page2PrefillBootstrapExtra = 0;
  /** loadDraftBootstrap 并发/递归重入计数，避免提前关掉遮罩 */
  var __dgBootstrapLoadingDepth = 0;
  /** 质量管理体系文件清单：中文名 ↔ 英文名（由 scripts/build_iso13485_name_match_data.py 从 xlsx 生成） */
  var __iso13485DocPairs = null;
  /** @type {Promise<any[]> | null} */
  var __iso13485DocPairsPromise = null;
  var _dgJobsPage = 1;
  var _dgJobsTotalPages = 1;

  var _dgAuthorRoleUserTouched = false;
  var _dgAuthorRoleAutoSig = "";
  var _dgAuthRoleTimer = null;
  var __page2DidTemplatePrefill = false;

  function parsePage2PrefillFromLocation() {
    try {
      var q = new URLSearchParams(window.location.search || "");
      if (!q.get("from") && !q.get("upload_id")) return null;
      var apid = (q.get("aicheckword_project_id") || "").trim();
      if (!apid && q.get("project_id")) {
        var p0 = String(q.get("project_id")).trim();
        if (/^\d+$/.test(p0)) apid = p0;
      }
      var bcRaw = (q.get("base_case_id") || q.get("base_case") || "").trim();
      var bcn = parseInt(bcRaw, 10);
      return {
        fromPage2: true,
        upload_id: (q.get("upload_id") || "").trim(),
        project_name: (q.get("project_name") || "").trim(),
        file_name: (q.get("file_name") || "").trim(),
        product: (q.get("product") || "").trim(),
        country: (q.get("country") || "").trim(),
        collection: (q.get("collection") || "").trim(),
        base_case_id: isNaN(bcn) || bcn <= 0 ? null : bcn,
        aicheckword_project_id: (function () {
          if (!apid) return null;
          var n = parseInt(apid, 10);
          return isNaN(n) || n <= 0 ? null : n;
        })(),
      };
    } catch (e) {
      return null;
    }
  }

  function getPage2Prefill() {
    if (__page2Prefill === null) __page2Prefill = parsePage2PrefillFromLocation();
    return __page2Prefill;
  }

  function _hasCjk(s) {
    return /[\u4e00-\u9fff]/.test(String(s || ""));
  }

  function classifyRegRouteFromAiwordCountry(countryRaw) {
    var s = _normCountryKey(countryRaw);
    if (!s) return "default";
    if (
      s === "cn" ||
      s === "china" ||
      s.indexOf("china ") === 0 ||
      s.indexOf(" china") >= 0 ||
      s.indexOf("people's republic of china") >= 0 ||
      s.indexOf("prc") >= 0 ||
      s === "nmpa" ||
      s.indexOf("nmpa") >= 0 ||
      s.indexOf("chinese mainland") >= 0
    ) {
      return "nmpa";
    }
    if (s.indexOf("中国") >= 0 || s.indexOf("药监局") >= 0 || s.indexOf("境内") >= 0) return "nmpa";

    if (
      s === "us" ||
      s === "usa" ||
      s.indexOf("united states") >= 0 ||
      s.indexOf("u.s.") >= 0 ||
      s.indexOf("america") >= 0 ||
      s === "fda" ||
      s.indexOf("fda") >= 0
    ) {
      return "fda";
    }
    if (s.indexOf("美国") >= 0) return "fda";

    if (
      s === "eu" ||
      s.indexOf("european union") >= 0 ||
      s.indexOf("europe") >= 0 ||
      /\bce\b/.test(s) ||
      s.indexOf("eea") >= 0
    ) {
      return "ce";
    }
    if (s.indexOf("欧盟") >= 0 || s.indexOf("欧洲") >= 0) return "ce";

    return "default";
  }

  /** FDA/CE → 优先英文版案例；NMPA → 优先中文版案例（与案例 document_language 对齐，用于下拉排序与同分择优） */
  function sortCasesByDocumentLanguageRoute(cases, route) {
    if (!Array.isArray(cases) || cases.length < 2) return cases || [];
    function rank(d) {
      var x = String(d || "").toLowerCase();
      if (route === "fda" || route === "ce") {
        if (x === "en") return 2;
        if (x === "both") return 1;
        return 0;
      }
      if (route === "nmpa") {
        if (x === "zh") return 2;
        if (x === "both") return 1;
        return 0;
      }
      return 0;
    }
    return cases.slice().sort(function (a, b) {
      var ra = rank(a.documentLanguage);
      var rb = rank(b.documentLanguage);
      if (rb !== ra) return rb - ra;
      var ida = Number(a.id) || 0;
      var idb = Number(b.id) || 0;
      return idb - ida;
    });
  }

  function docLangTieRank(route, docLang) {
    var x = String(docLang || "").toLowerCase();
    if (route === "fda" || route === "ce") {
      if (x === "en") return 2;
      if (x === "both") return 1;
      return 0;
    }
    if (route === "nmpa") {
      if (x === "zh") return 2;
      if (x === "both") return 1;
      return 0;
    }
    return 0;
  }

  function _normCountryKey(s) {
    return String(s || "")
      .trim()
      .toLowerCase()
      .replace(/[，,、]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  /**
   * 与 aicheckword 国家一致：仅用英文列 registration_country_en 与页面2国家比对；
   * 英文列为空时不使用中文国家列参与匹配（避免与「英文写法」冲突）。
   */
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

  function pickBestCaseIdForPage2(cases, pf) {
    if (!pf || !cases || !cases.length) return null;
    var route = classifyRegRouteFromAiwordCountry(pf.country);
    var bestId = null;
    var bestSc = 0;
    var bestTr = -1;
    var bestIdNum = -1;
    cases.forEach(function (c) {
      var sc = scoreCaseForPage2Prefill(c, pf, route);
      var tr = docLangTieRank(route, c.documentLanguage);
      var idn = Number(c.id) || 0;
      if (sc > bestSc || (sc === bestSc && (tr > bestTr || (tr === bestTr && idn > bestIdNum)))) {
        bestSc = sc;
        bestTr = tr;
        bestIdNum = idn;
        bestId = c.id;
      }
    });
    return bestSc >= 80 ? bestId : null;
  }

  function scoreProjectForPage2Prefill(p, pf, route) {
    var needle = String(pf.project_name || "").trim();
    if (!needle) return 0;
    var sc = 0;
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
    var aux = String(pf.product || "").trim();
    if (aux) {
      sc += Math.max(
        _scoreNamePair(aux, p.productName),
        Math.floor(_scoreNamePair(aux, p.productNameEn) * 0.85)
      );
    }
    if (_countryMatchAgainstAicheckwordEn(pf.country, p.registrationCountryEn)) sc += 40;
    var nm = String(p.name || "").trim();
    if (nm && (nm.indexOf(needle) >= 0 || needle.indexOf(nm) >= 0)) sc += 35;
    return sc;
  }

  function pickBestProjectIdForPage2(projects, pf) {
    if (!pf || !projects || !projects.length) return null;
    var route = classifyRegRouteFromAiwordCountry(pf.country);
    var bestId = null;
    var bestSc = 0;
    projects.forEach(function (p) {
      var sc = scoreProjectForPage2Prefill(p, pf, route);
      if (sc > bestSc) {
        bestSc = sc;
        bestId = p.id;
      }
    });
    return bestSc >= 80 ? bestId : null;
  }

  function stripExt(n) {
    var s = String(n || "").trim();
    var ix = s.lastIndexOf(".");
    if (ix > 1) s = s.slice(0, ix);
    return s.trim();
  }

  /** 去掉「附件3」「附录A」「Annex 2」等常见前缀，便于任务名与模板文件名语义对齐 */
  function stripLeadingDocTitleNoise(name) {
    var s = String(name || "").trim().replace(/\u3000/g, " ");
    if (!s) return s;
    var prev;
    var guard = 0;
    while (guard < 10) {
      guard += 1;
      prev = s;
      s = s
        .replace(/^附\s*件\s*(?:\d+|[\u4e00-\u9fff]|[A-Za-z])+\s*[,，、:：._\-\u3000]?\s*/i, "")
        .replace(/^附\s*录\s*(?:\d+|[\u4e00-\u9fff]|[A-Za-z])+\s*[,，、:：._\-\u3000]?\s*/i, "")
        .replace(/^附录\s*\d+\s*[,，、:：._\-\u3000]?\s*/i, "")
        .replace(/^Annex\s*(?:[A-Z]|\d+)\s*[,，、:：._\-\u3000]?\s*/i, "")
        .replace(/^Appendix\s*(?:[A-Z]|\d+)\s*[,，、:：._\-\u3000]?\s*/i, "")
        .replace(/^Attachment\s*\d+\s*[,，、:：._\-\u3000]?\s*/i, "")
        .replace(/^\[([^\]]{0,48})\]\s*/, "");
      s = s.trim();
      if (s === prev) break;
    }
    return s.trim();
  }

  /** 去掉尾部「（V1）」「_v2」等弱版本标记，减少与模板标题轻微差异 */
  function stripTrailingDocVersionNoise(name) {
    return String(name || "")
      .replace(/[（(]\s*[Vv]?\d+(?:\.\d+)?\s*[）)]\s*$/i, "")
      .replace(/\s*[_\-]\s*(?:V|v)?\d+(?:\.\d+)?\s*$/i, "")
      .trim();
  }

  /** 页面2模板预匹配：统一去扩展名 + 去附件类前缀 + 去尾部版本噪声后的「核心标题」 */
  function page2NormalizedDocTitleCore(fileName) {
    return stripTrailingDocVersionNoise(stripLeadingDocTitleNoise(stripExt(String(fileName || ""))));
  }

  /**
   * 页面2任务「文件名称」常为中文，模板案例库文件名多为英文/缩写。
   * 用可扩展词典将中文标题映射为英文子串，再与模板文件名做包含匹配（无翻译 API、离线可用）。
   */
  var PAGE2_ZH_FILE_TITLE_HINTS = [
    {
      pat: "软件需求|(?<!系统)需求规格|SRS",
      hints: [
        "软件需求规范",
        "软件需求",
        "需求规格",
        "software requirements specification",
        "software requirement specification",
        "software requirement",
        "software requirements",
        "srs",
        "swrs",
      ],
    },
    { pat: "系统需求|系统规格", hints: ["syrs", "system requirement", "system requirements"] },
    { pat: "软件设计|设计规范|概要设计|详细设计|SDS", hints: ["sds", "software design", "design specification", "detailed design"] },
    { pat: "软件架构|体系结构|架构设计", hints: ["architecture", "arch", "sad", "software architecture"] },
    /* 拆开：含「风险分析」的任务不应只靠 risk/risk management 命中「风险管理计划」类模板 */
    { pat: "风险分析", hints: ["风险分析", "risk analysis", "analysis of risk"] },
    { pat: "风险管理", hints: ["风险管理", "risk management", "rmf"] },
    { pat: "开发生命周期|生命周期|软件生存周期", hints: ["lifecycle", "sdlc", "software lifecycle"] },
    { pat: "验证|确认", hints: ["verification", "validation", "iq", "oq", "pq"] },
    { pat: "测试计划|测试方案", hints: ["test plan", "test protocol", "testing plan"] },
    { pat: "测试报告|验证报告", hints: ["test report", "verification report", "validation report"] },
    { pat: "可追溯|追溯性|追溯矩阵", hints: ["traceability", "trace", "rtm"] },
    { pat: "网络安全|信息安全", hints: ["cybersecurity", "cyber security", "security"] },
    /* 中文核心词放前；泛化英文靠后，避免「总结性可用性操作说明」仅靠 usability/manual 误胜 */
    {
      pat: "用户手册|使用手册",
      hints: ["说明书", "使用说明", "用户手册", "使用手册", "ifu", "instruction for use", "dfu", "user manual", "labeling", "manual", "instruction"],
    },
    { pat: "说明书|使用说明|标签", hints: ["说明书", "使用说明", "ifu", "instruction", "labeling", "manual", "user manual", "dfu"] },
    { pat: "可用性|人因|可用性工程", hints: ["usability", "human factor", "human factors", "ue"] },
    { pat: "配置管理|发布管理|版本管理", hints: ["configuration", "release", "scm", "version"] },
    { pat: "维护|售后|上市后", hints: ["maintenance", "postmarket", "post market", "surveillance"] },
    { pat: "部署|安装", hints: ["deployment", "installation"] },
    { pat: "性能|效率", hints: ["performance"] },
    { pat: "需求分析|立项", hints: ["requirement", "proposal"] },
    { pat: "用户需求|URS", hints: ["用户需求", "用户需求规范", "user requirement", "user requirements", "urs"] },
    { pat: "临床评价|临床评估", hints: ["clinical", "clinical evaluation"] },
    { pat: "同品种|对比器械", hints: ["predicate", "substantial equivalence"] },
    { pat: "技术审查|审评", hints: ["review", "technical review"] },
  ];

  function collectEnHintsFromZhPage2FileName(taskFileName) {
    var raw = String(taskFileName || "").trim().replace(/\u3000/g, " ");
    if (!raw) return [];
    var stems = [raw];
    var sx = stripExt(raw);
    if (sx && sx !== raw) stems.push(sx);
    var hints = [];
    var seen = {};
    function add(h) {
      var x = String(h || "").toLowerCase().trim();
      if (x.length < 2 || seen[x]) return;
      seen[x] = true;
      hints.push(x);
    }
    var k, si, t;
    for (si = 0; si < stems.length; si++) {
      t = stems[si];
      if (!t) continue;
      for (k = 0; k < PAGE2_ZH_FILE_TITLE_HINTS.length; k++) {
        var row = PAGE2_ZH_FILE_TITLE_HINTS[k];
        try {
          if (!new RegExp(row.pat).test(t)) continue;
        } catch (e) {
          continue;
        }
        var j;
        for (j = 0; j < row.hints.length; j++) add(row.hints[j]);
      }
    }
    return hints;
  }

  function loadIso13485DocNamePairs() {
    if (__iso13485DocPairs !== null) return Promise.resolve(__iso13485DocPairs);
    if (__iso13485DocPairsPromise) return __iso13485DocPairsPromise;
    var url = root + "/static/data/iso13485_document_name_pairs.json";
    __iso13485DocPairsPromise = fetch(url, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) {
        if (!r.ok) return { pairs: [] };
        return r.json();
      })
      .catch(function () {
        return { pairs: [] };
      })
      .then(function (j) {
        var arr = j && Array.isArray(j.pairs) ? j.pairs : [];
        __iso13485DocPairs = arr;
        return arr;
      });
    return __iso13485DocPairsPromise;
  }

  function mergePage2TemplateHints(primary, secondary) {
    var seen = {};
    var out = [];
    function pushOne(arr) {
      var i, raw, key, use;
      for (i = 0; i < (arr || []).length; i++) {
        raw = String((arr || [])[i] || "").trim();
        if (raw.length < 2) continue;
        key = _hasCjk(raw) ? raw : raw.toLowerCase();
        if (seen[key]) continue;
        seen[key] = true;
        use = _hasCjk(raw) ? raw : raw.toLowerCase();
        out.push(use);
      }
    }
    pushOne(primary);
    pushOne(secondary);
    return out;
  }

  /**
   * 按《医疗器械质量管理体系文件清单》xlsx 中的中英文名称对，为任务文件名补充可匹配模板的关键词。
   */
  function collectIso13485HintsForTask(taskFileName) {
    var pairs = __iso13485DocPairs;
    if (!pairs || !pairs.length) return [];
    var raw = String(taskFileName || "").trim().replace(/\u3000/g, " ");
    if (!raw) return [];
    var stems = [raw];
    var sx = stripExt(raw);
    if (sx && sx !== raw) stems.push(sx);
    var n0 = page2NormalizedDocTitleCore(raw);
    if (n0 && stems.indexOf(n0) < 0) stems.push(n0);
    var seen = {};
    var out = [];
    function addToken(s) {
      var x = String(s || "").trim();
      if (x.length < 2) return;
      var key = _hasCjk(x) ? x : x.toLowerCase();
      if (seen[key]) return;
      seen[key] = true;
      out.push(_hasCjk(x) ? x : x.toLowerCase());
    }
    var pi, si, t, zh, en, tl, el, hitZh;
    for (pi = 0; pi < pairs.length; pi++) {
      zh = String((pairs[pi] && pairs[pi].zh) || "").trim();
      en = String((pairs[pi] && pairs[pi].en) || "").trim();
      if (zh.length < 2 || en.length < 2) continue;
      el = en.toLowerCase();
      for (si = 0; si < stems.length; si++) {
        t = stems[si];
        if (!t) continue;
        if (_hasCjk(t)) {
          if (!_hasCjk(zh)) continue;
          var tCore = page2NormalizedDocTitleCore(t);
          var zhCore = page2NormalizedDocTitleCore(zh);
          hitZh = false;
          if (zh.length >= 3) {
            hitZh =
              t.indexOf(zh) >= 0 ||
              (t.length >= 4 && zh.indexOf(t) >= 0) ||
              (tCore.length >= 3 &&
                zhCore.length >= 3 &&
                (zhCore.indexOf(tCore) >= 0 || tCore.indexOf(zhCore) >= 0));
          } else hitZh = t === zh || t.indexOf(zh) >= 0;
          if (!hitZh) continue;
          addToken(en);
          addToken(zh);
          break;
        }
        tl = t.toLowerCase();
        if (el.length < 3) continue;
        if (tl.indexOf(el) >= 0 || (tl.length >= 4 && el.indexOf(tl) >= 0)) {
          if (_hasCjk(zh)) addToken(zh);
          addToken(en);
          break;
        }
      }
    }
    return out;
  }

  /**
   * 任务语义与模板文件名不一致时的加减分（在基础命中分之后叠加）。
   * 例如：「可用性风险分析」不应因泛化子串命中「风险管理计划」；「用户手册」不应因「使用说明」子串命中「总结性可用性操作说明」。
   */
  function page2TemplateRankContextDelta(task, tid) {
    var t = String(task || "");
    var id = String(tid || "");
    var low = id.toLowerCase();
    var d = 0;
    var hasRA = /风险分析/.test(t);
    var hasRM = /风险管理/.test(t);
    var um = /用户手册|使用手册/.test(t);
    var taskUecSumm = /总结|summative|可用性工程|人因验证|总结性/.test(t);
    var tlo = t.toLowerCase();
    var taskSRS =
      (/软件需求/.test(t) ||
        /\bsrs\b/i.test(tlo) ||
        (/需求规格/.test(t) && !/系统需求/.test(t))) &&
      !/用户需求/.test(t);
    if (taskSRS) {
      var srsInTid =
        /软件需求|需求规格/.test(id) ||
        /\bsrs\b|\bswrs\b/i.test(low) ||
        /software[\s._-]*requirements?([\s._-]*specification)?/i.test(low);
      var ursInTid =
        /用户需求|用户\s*需求规范/.test(id) ||
        /\burs\b|user\s*requirements?\s*specification|user\s*requirement(s)?\s*spec/i.test(low);
      if (ursInTid && !srsInTid) d -= 520000;
      if (srsInTid) d += 75000;
    }
    if (hasRA && !hasRM) {
      if (/风险管理计划/.test(id) || /risk\s*management\s*plan/i.test(low)) d -= 420000;
    }
    if (hasRA && !hasRM) {
      var hasRASem = /风险分析|risk\s*analysis|analysis\s*of\s*risk/i.test(id);
      if (!hasRASem && /总结性可用|可用性操作说明|summative\s*usability/i.test(id)) d -= 320000;
    }
    if (um && !taskUecSumm) {
      if (/总结|summative|summariz|总结性|可用性工程|人因验证|uec/i.test(id)) d -= 450000;
      else if (/说明书|使用说明|ifu|dfu|instruction\s*for\s*use/i.test(id)) d += 88000;
    }
    return d;
  }

  function sortTemplateFileIdsForRoute(route, ids) {
    var r = route || "default";
    if (r !== "fda" && r !== "ce" && r !== "nmpa") return ids.slice();
    return ids.slice().sort(function (a, b) {
      var ca = _hasCjk(a) ? 1 : 0;
      var cb = _hasCjk(b) ? 1 : 0;
      if (r === "fda" || r === "ce") {
        if (ca !== cb) return ca - cb;
        return 0;
      }
      if (r === "nmpa") {
        if (ca !== cb) return cb - ca;
        return 0;
      }
      return 0;
    });
  }

  function templateFileIdsFromTemplates(templates) {
    return (templates || [])
      .map(function (t) {
        return String(t.id || "").trim();
      })
      .filter(Boolean);
  }

  /**
   * 页面2单条「初稿生成」：只勾选 1 个模板，取匹配度最高者（同分按监管排序列表中先出现的项）。
   * 层级：精确文件名 > 忽略大小写精确 > 子串(CJK，含去扩展名) > 去「附件N」等前缀后的核心标题互含 >
   * 词库/ISO 命中 > 英文模糊。
   */
  function pickBestTemplateForPage2Prefill(templates, fileName, routeOpt) {
    var task = String(fileName || "").trim().replace(/\u3000/g, " ");
    if (!task || !templates || !templates.length) return null;
    var route = routeOpt || "default";
    var ids = sortTemplateFileIdsForRoute(route, templateFileIdsFromTemplates(templates));
    var tl = task.toLowerCase();
    var bk = stripExt(task);
    var taskCore = page2NormalizedDocTitleCore(task);
    var hintArr = mergePage2TemplateHints(
      collectIso13485HintsForTask(task),
      _hasCjk(task) ? collectEnHintsFromZhPage2FileName(task) : []
    );
    var bestId = null;
    var bestRank = -1e15;
    var bestTieLen = 1e9;
    var k;
    for (k = 0; k < ids.length; k++) {
      var tid = ids[k];
      var rank = 0;
      var cjkCtx = _hasCjk(task) || _hasCjk(tid);
      var bt0 = stripExt(tid);
      var tidCore = page2NormalizedDocTitleCore(tid);
      if (tid === task) rank = 1e6;
      else if (tid.toLowerCase() === tl) rank = 9e5;
      else if (cjkCtx) {
        /* 用无扩展名 bk，避免「.xlsx 任务名」无法被「.docx 模板」包含 */
        if (tid.indexOf(bk) >= 0 || bt0.indexOf(bk) >= 0 || bk.indexOf(bt0) >= 0) rank = 5e5;
        else if (
          taskCore.length >= 3 &&
          tidCore.length >= 3 &&
          (tidCore.indexOf(taskCore) >= 0 || taskCore.indexOf(tidCore) >= 0)
        )
          rank = taskCore === tidCore && taskCore.length >= 4 ? 518000 : 5e5;
      }
      if (!rank && hintArr.length) {
        var hi;
        for (hi = 0; hi < hintArr.length; hi++) {
          var h = String(hintArr[hi] || "");
          if (!h || h.length < 2) continue;
          var piece = 0;
          if (_hasCjk(h)) {
            var tidStr = String(tid);
            if (tidStr.indexOf(h) >= 0 || bt0.indexOf(h) >= 0 || tidCore.indexOf(h) >= 0) {
              piece = 2e5 + Math.min(5e4, h.length * 800);
            }
          } else if (tid.toLowerCase().indexOf(h.toLowerCase()) >= 0) {
            piece = 15e4 + Math.min(4e4, h.length * 400);
          }
          if (piece > rank) rank = piece;
        }
      }
      if (!rank) {
        var lo = tid.toLowerCase();
        if (lo.indexOf(tl) >= 0 || tl.indexOf(lo) >= 0) rank = 12e4;
        else {
          var b1 = stripExt(tid).toLowerCase();
          var b2 = stripExt(task).toLowerCase();
          if (b1 && b2 && (b1.indexOf(b2) >= 0 || b2.indexOf(b1) >= 0)) rank = 11e4;
        }
      }
      rank += page2TemplateRankContextDelta(task, tid);
      var tieLen = stripExt(tid).length;
      if (rank > bestRank || (rank === bestRank && tieLen < bestTieLen)) {
        bestRank = rank;
        bestTieLen = tieLen;
        bestId = tid;
      }
    }
    return bestRank > 0 && bestId ? bestId : null;
  }

  function applyTemplatePrefillForPage2(b, pf) {
    if (!pf || !b.templates) return;
    var route = classifyRegRouteFromAiwordCountry(pf.country);
    var one = pickBestTemplateForPage2Prefill(b.templates, pf.file_name, route);
    if (!one) return;
    var scope = el("dg_template_scope");
    if (scope) scope.value = "selected";
    syncTemplateFilesUiDisabled();
    var box = el("dg_template_files_box");
    if (!box) return;
    var pick = {};
    pick[String(one).trim()] = true;
    box.querySelectorAll('input[type="checkbox"][data-template-name]').forEach(function (inp) {
      var v = (inp.getAttribute("data-template-name") || "").trim();
      inp.checked = !!pick[v];
    });
    reorderTemplateCheckboxesSelectedFirst();
    updateTemplateSelectionSummary();
    __page2DidTemplatePrefill = true;
    setPrefillBadge("templates", true);
  }

  function clearTaskBaseHintUi() {
    _dgBaseUploadId = "";
    var w = el("dg_task_base_hint_wrap");
    if (w) w.classList.add("d-none");
    var inp = el("dg_task_base_ftp_display");
    if (inp) inp.value = "";
  }

  function formatTaskBaseFtpDisplay(j) {
    if (!j) return "";
    var name = (j.templateFileName || j.fileName || "").trim();
    var ftpShown = (j.ftpPathDisplay || j.ftpPath || "").trim();
    if (name && ftpShown) {
      return "文件：" + name + "\n\nFTP：" + ftpShown;
    }
    return ftpShown || name || "";
  }

  function loadTaskBaseForPage2Prefill(uploadId) {
    var w = el("dg_task_base_hint_wrap");
    var inp = el("dg_task_base_ftp_display");
    if (w) w.classList.remove("d-none");
    if (inp) inp.value = "加载中…";
    api("/draft-gen/api/task-base?upload_id=" + encodeURIComponent(uploadId), { method: "GET" }).then(function (x) {
      if (!inp) return;
      if (!x.ok || !x.json) {
        inp.value = (x.json && x.json.message) || "加载失败";
        _dgBaseUploadId = "";
        return;
      }
      var j = x.json;
      if (j.source === "ftp" && j.ftpPath) {
        inp.value = formatTaskBaseFtpDisplay(j);
        _dgBaseUploadId = uploadId;
      } else if (j.source === "blob") {
        var blobName = (j.templateFileName || j.fileName || "").trim();
        inp.value = blobName
          ? "文件：" + blobName + "\n（库内模板，提交时由服务端读取作 Base）"
          : "（库内模板文件，提交时由服务端读取作 Base）";
        _dgBaseUploadId = uploadId;
      } else {
        inp.value = "";
        _dgBaseUploadId = "";
        showMsg("当前任务无模板文件（例如仅为链接），请手动选择 Base。", false);
      }
    }).catch(function () {
      if (inp) inp.value = "请求失败";
      _dgBaseUploadId = "";
    });
  }

  function maybeApplyPage2PrefillAfterBootstrap(b) {
    var pf = getPage2Prefill();
    if (!pf || !pf.fromPage2 || __page2PrefillApplied) return false;
    if (__page2PrefillBootstrapExtra > 8) {
      __page2PrefillApplied = true;
      return false;
    }
    var needReload = false;
    var bcEl = el("dg_base_case");
    if (bcEl) {
      var targetBc = null;
      if (pf.base_case_id) {
        var ids0 = (b.cases || []).map(function (c) { return String(c.id); });
        if (ids0.indexOf(String(pf.base_case_id)) >= 0) targetBc = String(pf.base_case_id);
      }
      if (!targetBc) targetBc = pickBestCaseIdForPage2(b.cases || [], pf);
      if (targetBc && String(bcEl.value || "") !== String(targetBc)) {
        var ids2 = (b.cases || []).map(function (c) { return String(c.id); });
        if (ids2.indexOf(String(targetBc)) >= 0) {
          bcEl.value = String(targetBc);
          needReload = true;
        }
      }
    }
    if (needReload) {
      __page2PrefillBootstrapExtra += 1;
      return true;
    }
    var pm = el("dg_project_mode");
    var pidSel = el("dg_project_id");
    if (pm && pidSel && pf.aicheckword_project_id) {
      var want = String(pf.aicheckword_project_id);
      var opts = Array.prototype.map.call(pidSel.options, function (o) { return String(o.value); });
      if (opts.indexOf(want) >= 0) {
        pm.value = "existing";
        pidSel.value = want;
        syncProjectUi();
      }
    } else if (pm && pidSel) {
      var bestPid = pickBestProjectIdForPage2(b.projects || [], pf);
      if (bestPid) {
        pm.value = "existing";
        pidSel.value = String(bestPid);
        syncProjectUi();
      } else if (pf.project_name) {
        var pnl = pf.project_name.toLowerCase();
        var bestVal = null;
        Array.prototype.forEach.call(pidSel.options, function (o) {
          if (!o.value) return;
          if ((o.textContent || "").toLowerCase().indexOf(pnl) >= 0) bestVal = o.value;
        });
        if (bestVal) {
          pm.value = "existing";
          pidSel.value = bestVal;
          syncProjectUi();
        }
      }
    }
    applyTemplatePrefillForPage2(b, pf);
    if (pf.upload_id) {
      loadTaskBaseForPage2Prefill(pf.upload_id);
    } else {
      clearTaskBaseHintUi();
    }
    __page2PrefillApplied = true;
    showMsg(
      "已从" + dgUserText("页面2", "我的") + "任务按规则匹配案例/项目/模板（请核对）。中文文件名会经内置词库映射为英文关键词后再对齐模板库文件名；可按需修改后提交初稿。",
      false
    );
    return false;
  }

  function draftFileKey(f) {
    return f && f.name ? f.name + "\0" + String(f.size) + "\0" + String(f.lastModified) : "";
  }

  function draftMergeFiles(target, fileList) {
    var seen = {};
    var i;
    for (i = 0; i < target.length; i += 1) {
      seen[draftFileKey(target[i])] = true;
    }
    var arr = fileList ? Array.prototype.slice.call(fileList, 0) : [];
    for (i = 0; i < arr.length; i += 1) {
      var f = arr[i];
      var k = draftFileKey(f);
      if (k && !seen[k]) {
        seen[k] = true;
        target.push(f);
      }
    }
  }

  function draftRenderFileList(accum, ulId, countId) {
    var ul = el(ulId);
    var cap = el(countId);
    if (!ul) return;
    ul.innerHTML = "";
    var j;
    for (j = 0; j < accum.length; j += 1) {
      (function (idx) {
        var f = accum[idx];
        var li = document.createElement("li");
        li.className = "list-group-item d-flex justify-content-between align-items-center py-1 px-2";
        var span = document.createElement("span");
        span.className = "text-break me-2";
        span.textContent = f.name + " (" + (f.size < 1024 ? f.size + " B" : Math.ceil(f.size / 1024) + " KB") + ")";
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-sm btn-link text-danger text-nowrap p-0";
        btn.textContent = "移除";
        btn.addEventListener("click", function () {
          accum.splice(idx, 1);
          draftRenderFileList(accum, ulId, countId);
        });
        li.appendChild(span);
        li.appendChild(btn);
        ul.appendChild(li);
      })(j);
    }
    if (cap) cap.textContent = accum.length ? "已选 " + accum.length + " 个文件" : "尚未选择文件";
  }

  function wireDraftFilePickers() {
    if (_dgFilePickersWired) return;
    var pickIn = el("dg_input_files_picker");
    var pickBase = el("dg_base_files_picker");
    if (!pickIn && !pickBase) return;
    if (pickIn) {
      pickIn.setAttribute("accept", DRAFT_UPLOAD_ACCEPT);
      pickIn.addEventListener("change", function () {
        if (pickIn.files && pickIn.files.length) draftMergeFiles(_dgInputFilesAccum, pickIn.files);
        pickIn.value = "";
        draftRenderFileList(_dgInputFilesAccum, "dg_input_files_list", "dg_input_files_count");
      });
    }
    if (pickBase) {
      pickBase.setAttribute("accept", DRAFT_UPLOAD_ACCEPT);
      pickBase.addEventListener("change", function () {
        if (pickBase.files && pickBase.files.length) draftMergeFiles(_dgBaseFilesAccum, pickBase.files);
        pickBase.value = "";
        draftRenderFileList(_dgBaseFilesAccum, "dg_base_files_list", "dg_base_files_count");
      });
    }
    var bi = el("dg_btn_pick_input");
    if (bi && pickIn) bi.addEventListener("click", function () { pickIn.click(); });
    var bb = el("dg_btn_pick_base");
    if (bb && pickBase) bb.addEventListener("click", function () { pickBase.click(); });
    var ci = el("dg_btn_clear_input");
    if (ci) ci.addEventListener("click", function () {
      _dgInputFilesAccum.length = 0;
      draftRenderFileList(_dgInputFilesAccum, "dg_input_files_list", "dg_input_files_count");
    });
    var cb = el("dg_btn_clear_base");
    if (cb) cb.addEventListener("click", function () {
      _dgBaseFilesAccum.length = 0;
      draftRenderFileList(_dgBaseFilesAccum, "dg_base_files_list", "dg_base_files_count");
    });
    draftRenderFileList(_dgInputFilesAccum, "dg_input_files_list", "dg_input_files_count");
    draftRenderFileList(_dgBaseFilesAccum, "dg_base_files_list", "dg_base_files_count");
    _dgFilePickersWired = true;
  }

  function api(path, opts) {
    const url = root + path;
    const o = opts || {};
    return fetch(url, Object.assign({ credentials: "same-origin" }, o)).then(function (r) {
      return r.text().then(function (text) {
        var j = null;
        try {
          j = text ? JSON.parse(text) : {};
        } catch (e) {
          j = {
            message:
              "非 JSON 响应（HTTP " +
              r.status +
              "）：" +
              String(text || "").replace(/\s+/g, " ").slice(0, 240),
          };
        }
        return { ok: r.ok, status: r.status, json: j };
      });
    });
  }

  function el(id) {
    return document.getElementById(id);
  }

  function setDraftBootstrapLoadingVisible(on, optMsg) {
    var w = el("dg_bootstrap_loading");
    if (!w) return;
    var t = el("dg_bootstrap_loading_text");
    if (t && optMsg) t.textContent = String(optMsg);
    if (on) {
      w.classList.remove("d-none");
      w.classList.add("d-flex");
      w.setAttribute("aria-hidden", "false");
    } else {
      w.classList.add("d-none");
      w.classList.remove("d-flex");
      w.setAttribute("aria-hidden", "true");
    }
  }

  function beginDraftBootstrapLoading() {
    __dgBootstrapLoadingDepth += 1;
    if (__dgBootstrapLoadingDepth === 1) setDraftBootstrapLoadingVisible(true);
  }

  function endDraftBootstrapLoading() {
    __dgBootstrapLoadingDepth -= 1;
    if (__dgBootstrapLoadingDepth <= 0) {
      __dgBootstrapLoadingDepth = 0;
      setDraftBootstrapLoadingVisible(false);
    }
  }

  function showMsg(text, isErr) {
    const box = el("dg_msg");
    if (box) {
      box.textContent = text || "";
      box.className = "alert " + (isErr ? "alert-danger" : "alert-info");
      box.classList.remove("d-none");
    }
    if (window.PageToast && window.PageToast.maybeToastFor(box, text, isErr)) {
      return;
    }
  }

  var DG_STATUS_ZH = {
    pending: "排队中",
    queued: "排队中",
    running: "运行中",
    succeeded: "成功",
    failed: "失败",
  };

  function dgStatusZh(st) {
    var s = (st || "").toLowerCase();
    return DG_STATUS_ZH[s] || st || "";
  }

  function draftProgressSetVisible(show) {
    var w = el("dg_progress_wrap");
    if (!w) return;
    if (show) w.classList.remove("d-none");
    else w.classList.add("d-none");
  }

  /** 进度区标题：勿写死「正在生成」，失败/超时后须改为已结束类文案 */
  function draftProgressSetHeadline(text) {
    var h = el("dg_progress_headline");
    if (!h) return;
    h.textContent = text != null ? String(text) : "";
  }

  function draftProgressResetBarStyle() {
    var bar = el("dg_progress_bar");
    if (!bar) return;
    bar.classList.remove("bg-success", "bg-danger");
    bar.classList.add("bg-primary");
  }

  function draftProgressSetRunningStyle(running) {
    var bar = el("dg_progress_bar");
    if (!bar) return;
    draftProgressResetBarStyle();
    if (running) {
      bar.classList.add("progress-bar-striped", "progress-bar-animated");
    } else {
      bar.classList.remove("progress-bar-striped", "progress-bar-animated");
    }
  }

  function draftProgressSetTerminal(ok) {
    var bar = el("dg_progress_bar");
    if (!bar) return;
    bar.classList.remove("progress-bar-striped", "progress-bar-animated", "bg-primary");
    bar.classList.add(ok ? "bg-success" : "bg-danger");
  }

  function draftProgressUpdate(pct01, caption, pollLine) {
    var bar = el("dg_progress_bar");
    var cap = el("dg_progress_caption");
    var pol = el("dg_poll_status");
    var n = typeof pct01 === "number" && !isNaN(pct01) ? pct01 : 0;
    if (n > 1) n = n / 100;
    n = Math.max(0, Math.min(1, n));
    var p100 = Math.round(n * 100);
    if (bar) {
      bar.style.width = p100 + "%";
      bar.textContent = p100 + "%";
    }
    if (cap) cap.textContent = caption || "处理中…";
    if (pol) pol.textContent = pollLine || "";
  }

  function rebuildProviderSelect(rows) {
    const sel = el("dg_provider");
    if (!sel || !Array.isArray(rows) || !rows.length) return;
    const cur = (sel.value || "deepseek").trim();
    sel.innerHTML = "";
    rows.forEach(function (r) {
      const id = (r.id || "").trim();
      if (!id) return;
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = r.label || id;
      sel.appendChild(opt);
    });
    const ids = rows.map(function (r) { return (r.id || "").trim(); }).filter(Boolean);
    if (ids.indexOf(cur) >= 0) sel.value = cur;
    else sel.selectedIndex = 0;
  }

  function showInteropInfo(d) {
    const box = el("dg_interop_info");
    if (!box) return;
    const parts = [];
    if (d && d.adminNotes) parts.push(String(d.adminNotes));
    if (d && Array.isArray(d.interopSyncWarnings) && d.interopSyncWarnings.length) {
      d.interopSyncWarnings.forEach(function (w) { parts.push(String(w)); });
    }
    if (!parts.length) {
      box.classList.add("d-none");
      box.textContent = "";
      return;
    }
    box.textContent = parts.join("\n\n");
    box.classList.remove("d-none");
  }

  function syncLlmProviderUi() {
    const prov = (el("dg_provider") && el("dg_provider").value) || "deepseek";
    const keyInp = el("dg_api_key");
    const hint = el("dg_key_hint");
    const sub = el("dg_provider_hint");
    const klab = el("dg_key_label");
    var pmap = lastHasApiKeyByProvider || {};
    var hasThis = Object.prototype.hasOwnProperty.call(pmap, prov) ? !!pmap[prov] : !!lastHasLlmKey;
    var reqPersonal = !!lastPersonalKeysOnly;
    var keyRequired = reqPersonal;
    if (prov === "cursor") {
      if (keyInp) keyInp.disabled = false;
      if (klab) klab.textContent = keyRequired ? "Cursor API Key（必填）" : "Cursor API Key（可选）";
      if (hint) {
        hint.textContent = hasThis
          ? "已加密落库（仅本账号），重启后仍有效；输入框不留存明文（留空则不修改）"
          : keyRequired
            ? "当前账号尚未保存 Key，须填写并保存"
            : dgUserText(
                "未保存时将使用 aicheckword 系统 Cursor Key",
                "未保存时将使用系统 Cursor Key"
              );
      }
      if (sub) {
        sub.textContent = reqPersonal
          ? dgUserText(
              "本账号个人 Key，他人不可共用；生成任务使用当前下拉所选提供方（须已保存 Key）。GitHub 仓库与 ref 由管理员在 aicheckword 配 cursor_*。",
              "本账号个人 Key，他人不可共用；生成任务使用当前下拉所选提供方（须已保存 Key）。GitHub 仓库与 ref 由管理员配置。"
            )
          : dgUserText(
              "未配置个人 Key 时使用 aicheckword 系统 Key；已保存个人 Key 则优先使用。GitHub 仓库与 ref 由管理员在 aicheckword 配 cursor_*。",
              "未配置个人 Key 时使用系统 Key；已保存个人 Key 则优先使用。GitHub 仓库与 ref 由管理员配置。"
            );
      }
    } else if (prov === "tongyi") {
      if (keyInp) keyInp.disabled = false;
      if (klab) klab.textContent = keyRequired ? "DashScope API Key（必填）" : "DashScope API Key（可选）";
      if (hint) {
        hint.textContent = hasThis
          ? "已加密落库（仅本账号），重启后仍有效；输入框不留存明文（留空则不修改）"
          : keyRequired
            ? "当前账号尚未保存 Key，须填写并保存"
            : dgUserText(
                "未保存时将使用 aicheckword 系统通义 Key",
                "未保存时将使用系统通义 Key"
              );
      }
      if (sub) {
        sub.textContent = reqPersonal
          ? "本账号个人 Key，他人不可共用；模型名可空（系统默认）。API Base 对通义通常留空（官方端点）。"
          : dgUserText(
              "未配置个人 Key 时使用 aicheckword 系统 Key；已保存个人 Key 则优先使用。模型名可空。",
              "未配置个人 Key 时使用系统 Key；已保存个人 Key 则优先使用。模型名可空。"
            );
      }
    } else {
      if (keyInp) keyInp.disabled = false;
      if (klab) klab.textContent = keyRequired ? "DeepSeek API Key（必填）" : "DeepSeek API Key（可选）";
      if (hint) {
        hint.textContent = hasThis
          ? "已加密落库（仅本账号），重启后仍有效；输入框不留存明文（留空则不修改）"
          : keyRequired
            ? "当前账号尚未保存 Key，须填写并保存"
            : dgUserText(
                "未保存时将使用 aicheckword 系统 DeepSeek Key",
                "未保存时将使用系统 DeepSeek Key"
              );
      }
      if (sub) {
        sub.textContent = reqPersonal
          ? dgUserText(
              "本账号个人 Key，他人不可共用；生成任务使用当前下拉所选 DeepSeek（须已保存 Key）。API Base / 模型可空则用系统默认。",
              "本账号个人 Key，他人不可共用；生成任务使用当前下拉所选 DeepSeek（须已保存 Key）。API Base / 模型可空则用系统默认。"
            )
          : dgUserText(
              "未配置个人 Key 时使用 aicheckword 系统 Key；已保存个人 Key 则优先使用。API Base / 模型可空。",
              "未配置个人 Key 时使用系统 Key；已保存个人 Key 则优先使用。API Base / 模型可空。"
            );
      }
    }
  }

  function mergeProviderStringMap(src) {
    var o = { deepseek: "", cursor: "", tongyi: "" };
    if (src && typeof src === "object") {
      ["deepseek", "cursor", "tongyi"].forEach(function (k) {
        if (Object.prototype.hasOwnProperty.call(src, k) && src[k] != null) {
          o[k] = String(src[k]);
        }
      });
    }
    return o;
  }

  function stashLlmExtrasForProvider(prov) {
    if (!prov) return;
    var ab = el("dg_api_base_url");
    var lm = el("dg_llm_model");
    if (ab) lastApiBaseByProvider[prov] = ab.value;
    if (lm) lastLlmModelByProvider[prov] = lm.value;
  }

  function applyLlmExtrasFromMaps(prov) {
    var ab = el("dg_api_base_url");
    var lm = el("dg_llm_model");
    var b = lastApiBaseByProvider[prov];
    var m = lastLlmModelByProvider[prov];
    if (ab) ab.value = b != null ? b : "";
    if (lm) lm.value = m != null ? m : "";
  }

  function onProviderSelectChange() {
    var sel = el("dg_provider");
    if (!sel) return;
    var now = sel.value || "deepseek";
    stashLlmExtrasForProvider(lastLlmProviderSelection);
    lastLlmProviderSelection = now;
    applyLlmExtrasFromMaps(now);
    syncLlmProviderUi();
  }

  /**
   * @param {Array<{id?: string, label?: string}>} templates
   * @param {boolean} disabledAll 为 true 时禁用勾选（与「全部模板」模式一致）
   */
  function rebuildTemplateCheckboxes(templates, disabledAll) {
    const box = el("dg_template_files_box");
    if (!box) return;
    const prev = {};
    box.querySelectorAll('input[type="checkbox"][data-template-name]').forEach(function (inp) {
      const n = (inp.getAttribute("data-template-name") || "").trim();
      if (n) prev[n] = !!inp.checked;
    });
    box.innerHTML = "";
    if (!templates || !templates.length) {
      const p = document.createElement("p");
      p.className = "text-muted small mb-0";
      p.textContent = "请先选择「模板项目案例」并刷新列表；无模板文件名时此处为空。";
      box.appendChild(p);
      applyTemplateCheckboxFilter();
      updateTemplateSelectionSummary();
      return;
    }
    templates.forEach(function (row, idx) {
      row.__tplOrder = idx;
    });
    var ordered = templates.slice().sort(function (a, b) {
      var na = String(a.id != null ? a.id : "").trim();
      var nb = String(b.id != null ? b.id : "").trim();
      var ca = !!prev[na];
      var cb = !!prev[nb];
      if (ca !== cb) return ca ? -1 : 1;
      return (a.__tplOrder || 0) - (b.__tplOrder || 0);
    });
    ordered.forEach(function (row, idx) {
      const name = String(row.id != null ? row.id : "").trim();
      if (!name) return;
      const lab = String(row.label != null ? row.label : name);
      const wrap = document.createElement("div");
      wrap.className = "form-check";
      const inp = document.createElement("input");
      inp.type = "checkbox";
      inp.className = "form-check-input";
      inp.id = "dg_tpl_cb_" + idx;
      inp.value = name;
      inp.setAttribute("data-template-name", name);
      inp.setAttribute("data-disk-base", row.diskBaseAvailable === false ? "0" : "1");
      inp.checked = !!prev[name];
      inp.disabled = !!disabledAll;
      inp.addEventListener("change", function () {
        updateBaseRequirementUI();
        reorderTemplateCheckboxesSelectedFirst();
        updateTemplateSelectionSummary();
      });
      const lbl = document.createElement("label");
      lbl.className = "form-check-label";
      lbl.htmlFor = inp.id;
      lbl.textContent = lab + (row.diskBaseAvailable === false ? "（服务器无原件，需上传 Base）" : "");
      wrap.appendChild(inp);
      wrap.appendChild(lbl);
      box.appendChild(wrap);
    });
    applyTemplateCheckboxFilter();
    reorderTemplateCheckboxesSelectedFirst();
    updateTemplateSelectionSummary();
    updateBaseRequirementUI();
  }

  function selectedTemplatesMissingDiskBase() {
    var scope = (el("dg_template_scope") && el("dg_template_scope").value) || "selected";
    var templates = (lastBootstrap && lastBootstrap.templates) ? lastBootstrap.templates : [];
    var byId = {};
    templates.forEach(function (t) {
      if (t && t.id != null) byId[String(t.id)] = t;
    });
    var names = [];
    if (scope === "all") {
      templates.forEach(function (t) {
        var n = String((t && t.id) || "").trim();
        if (n) names.push(n);
      });
    } else {
      names = selectedTemplateNames();
    }
    return names.filter(function (n) {
      var row = byId[n];
      return row && row.diskBaseAvailable === false;
    });
  }

  function updateBaseRequirementUI() {
    var req = el("dg_lbl_base_req");
    var inplace = el("dg_inplace") && el("dg_inplace").value === "1";
    var missing = selectedTemplatesMissingDiskBase();
    var needBase = inplace && missing.length > 0;
    if (req) req.classList.toggle("d-none", !needBase);
  }

  function applyTemplateCheckboxFilter() {
    const fin = el("dg_template_filter");
    const n = (fin && fin.value) ? fin.value.trim().toLowerCase() : "";
    const box = el("dg_template_files_box");
    if (!box) return;
    box.querySelectorAll(".form-check").forEach(function (wrap) {
      const lbl = wrap.querySelector("label");
      const inp = wrap.querySelector("input[data-template-name]");
      const t = (lbl && lbl.textContent) ? lbl.textContent.toLowerCase() : "";
      const name = inp ? (inp.getAttribute("data-template-name") || "").toLowerCase() : "";
      const ok = !n || t.indexOf(n) >= 0 || name.indexOf(n) >= 0;
      wrap.style.display = ok ? "" : "none";
    });
  }

  /** @type {Record<string, { rows: any[], valueKey: string, labelKey: string, emptyOpt: {value?: string, label?: string}|null }>} */
  var SELECT_ROW_CACHE = {};

  function rememberSelectRows(selectId, rows, valueKey, labelKey, emptyOpt) {
    SELECT_ROW_CACHE[selectId] = {
      rows: Array.isArray(rows) ? rows.slice() : [],
      valueKey: valueKey,
      labelKey: labelKey,
      emptyOpt: emptyOpt ? { value: emptyOpt.value != null ? String(emptyOpt.value) : "", label: emptyOpt.label || "—" } : null,
    };
  }

  function fillSelect(selectId, rows, valueKey, labelKey, emptyOpt) {
    const sel = el(selectId);
    if (!sel) return;
    if (!Array.isArray(rows)) rows = [];
    const cur = (sel.value || "").trim();
    sel.innerHTML = "";
    if (emptyOpt) {
      const o0 = document.createElement("option");
      o0.value = emptyOpt.value != null ? String(emptyOpt.value) : "";
      o0.textContent = emptyOpt.label || "—";
      sel.appendChild(o0);
    }
    rows.forEach(function (r) {
      const v = String(r[valueKey] != null ? r[valueKey] : "");
      const lab = String(r[labelKey] != null ? r[labelKey] : v);
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = lab;
      sel.appendChild(opt);
    });
    const vals = Array.prototype.map.call(sel.options, function (o) { return o.value; });
    if (cur && vals.indexOf(cur) >= 0) sel.value = cur;
  }

  function fillYesNo(selectId, defaultYes) {
    const sel = el(selectId);
    if (!sel) return;
    const want = defaultYes ? "1" : "0";
    sel.innerHTML = "";
    [["1", "是"], ["0", "否"]].forEach(function (pair) {
      const opt = document.createElement("option");
      opt.value = pair[0];
      opt.textContent = pair[1];
      sel.appendChild(opt);
    });
    sel.value = want;
  }

  function applySelectSearchFilter(selectId) {
    const cache = SELECT_ROW_CACHE[selectId];
    const sel = el(selectId);
    if (!cache || !sel) return;
    const fin = el(selectId + "_filter");
    const needle = (fin && fin.value) ? fin.value.trim().toLowerCase() : "";
    const cur = (sel.value || "").trim();
    let rows = cache.rows;
    if (needle) {
      rows = cache.rows.filter(function (r) {
        const v = String(r[cache.valueKey] != null ? r[cache.valueKey] : "").toLowerCase();
        const lab = String(r[cache.labelKey] != null ? r[cache.labelKey] : v).toLowerCase();
        return v.indexOf(needle) >= 0 || lab.indexOf(needle) >= 0;
      });
    }
    fillSelect(selectId, rows, cache.valueKey, cache.labelKey, cache.emptyOpt);
    const vals = Array.prototype.map.call(sel.options, function (o) { return o.value; });
    if (cur && vals.indexOf(cur) < 0) {
      const opt = document.createElement("option");
      opt.value = cur;
      opt.textContent = "【已选】" + cur;
      sel.appendChild(opt);
      sel.value = cur;
    } else if (cur && vals.indexOf(cur) >= 0) {
      sel.value = cur;
    }
  }

  function fillSelectThenCache(selectId, rows, valueKey, labelKey, emptyOpt) {
    rememberSelectRows(selectId, rows, valueKey, labelKey, emptyOpt);
    fillSelect(selectId, rows, valueKey, labelKey, emptyOpt);
  }

  function setTemplateCheckboxesAll(checked) {
    const box = el("dg_template_files_box");
    if (!box) return;
    box.querySelectorAll('input[type="checkbox"][data-template-name]').forEach(function (inp) {
      if (inp.disabled) return;
      const wrap = inp.closest(".form-check");
      if (wrap && wrap.style.display === "none") return;
      inp.checked = !!checked;
    });
    reorderTemplateCheckboxesSelectedFirst();
    updateTemplateSelectionSummary();
    scheduleApplyAuthorRoleSuggestion();
    updateBaseRequirementUI();
  }
    const scope = (el("dg_template_scope") && el("dg_template_scope").value) || "selected";
    const disabled = scope === "all";
    const box = el("dg_template_files_box");
    if (!box) return;
    box.querySelectorAll('input[type="checkbox"][data-template-name]').forEach(function (inp) {
      inp.disabled = disabled;
    });
    var bar = el("dg_tpl_actions_bar");
    if (bar) bar.style.display = disabled ? "none" : "";
    applyTemplateCheckboxFilter();
    updateTemplateSelectionSummary();
    scheduleApplyAuthorRoleSuggestion();
    updateBaseRequirementUI();
  }
    const map = {
      inplace_patch: "dg_inplace_label",
      save_as_case: "dg_save_case_label",
      multi_base_auto_route: "dg_multi_route_label",
      docx_track_changes: "dg_track_label",
    };
    (rows || []).forEach(function (row) {
      const lid = map[row.id];
      if (!lid || !el(lid)) return;
      var lb = el(lid);
      var tx = lb.querySelector(".dg-lbl-text");
      var t = row.label || row.id;
      if (tx) tx.textContent = t;
      else lb.textContent = t;
    });
  }

  function setPrefillBadge(suffix, on) {
    var s = el("dg_pf_" + suffix);
    if (!s) return;
    if (on) s.classList.remove("d-none");
    else s.classList.add("d-none");
  }

  function clearAllPrefillBadges() {
    ["collection", "base_case", "templates", "project", "author", "inplace", "save_case", "multi_route", "track"].forEach(
      function (x) {
        setPrefillBadge(x, false);
      }
    );
  }

  function getSelectedCaseMeta() {
    var bc = el("dg_base_case");
    var id = bc && bc.value ? String(bc.value).trim() : "";
    if (!id || !lastBootstrap || !lastBootstrap.cases) return { registrationType: "", projectForm: "" };
    var i, rows = lastBootstrap.cases;
    for (i = 0; i < rows.length; i++) {
      if (String(rows[i].id) === id) {
        return {
          registrationType: String(rows[i].registrationType || rows[i].registration_type || "").trim(),
          projectForm: String(rows[i].projectForm || rows[i].project_form || "").trim(),
        };
      }
    }
    return { registrationType: "", projectForm: "" };
  }

  function namesForAuthorRoleInference() {
    var scope = (el("dg_template_scope") && el("dg_template_scope").value) || "selected";
    var tplList =
      lastBootstrap && lastBootstrap.templates
        ? lastBootstrap.templates
            .map(function (t) {
              return String(t.id || "").trim();
            })
            .filter(Boolean)
        : [];
    if (scope === "all") return tplList.slice();
    var sel = selectedTemplateNames();
    if (sel.length) return sel.slice();
    return tplList.slice();
  }

  function buildAuthorRoleSig() {
    var cm = getSelectedCaseMeta();
    var ns = namesForAuthorRoleInference().join("\0");
    return [cm.registrationType || "", cm.projectForm || "", ns].join("|");
  }

  function fetchSuggestAuthorRole() {
    if (_dgAuthorRoleUserTouched) return;
    var cm = getSelectedCaseMeta();
    var names = namesForAuthorRoleInference();
    var sig = buildAuthorRoleSig();
    var ar = el("dg_author_role");
    if (!ar || !ar.options.length) return;
    var usp = new URLSearchParams();
    if (cm.registrationType) usp.set("registration_type", cm.registrationType);
    if (cm.projectForm) usp.set("project_form", cm.projectForm);
    var i;
    for (i = 0; i < names.length; i++) usp.append("templates", names[i]);
    api("/draft-gen/api/suggest-author-role?" + usp.toString(), { method: "GET" }).then(function (x) {
      if (_dgAuthorRoleUserTouched) return;
      if (!x.ok || !x.json) return;
      var k = x.json.authorRole;
      if (k === undefined || k === null) return;
      var vals = Array.prototype.map.call(ar.options, function (o) {
        return o.value;
      });
      if (vals.indexOf(String(k)) < 0) return;
      ar.value = String(k);
      _dgAuthorRoleAutoSig = sig;
      setPrefillBadge("author", true);
    });
  }

  function scheduleApplyAuthorRoleSuggestion() {
    if (_dgAuthorRoleUserTouched) return;
    if (_dgAuthRoleTimer) window.clearTimeout(_dgAuthRoleTimer);
    _dgAuthRoleTimer = window.setTimeout(function () {
      _dgAuthRoleTimer = null;
      fetchSuggestAuthorRole();
    }, 180);
  }

  function applyAuthorRoleSuggestionAfterBootstrap(b) {
    var ar = el("dg_author_role");
    if (!ar || !b) return;
    var sug = b.suggestedAuthorRole;
    if (sug !== undefined && sug !== null) {
      var vals = Array.prototype.map.call(ar.options, function (o) {
        return o.value;
      });
      if (vals.indexOf(String(sug)) >= 0) {
        ar.value = String(sug);
        _dgAuthorRoleAutoSig = buildAuthorRoleSig();
        setPrefillBadge("author", true);
        return;
      }
    }
    fetchSuggestAuthorRole();
  }

  function updateDefaultFilledBadges(b, pf) {
    clearAllPrefillBadges();
    if (!b) return;
    var cel = el("dg_collection");
    if (pf && pf.collection && cel && String(cel.value || "") === String(pf.collection)) setPrefillBadge("collection", true);
    if (pf && pf.base_case_id && el("dg_base_case") && String(el("dg_base_case").value || "") === String(pf.base_case_id)) {
      setPrefillBadge("base_case", true);
    }
    if (__page2DidTemplatePrefill) setPrefillBadge("templates", true);
    if (pf && pf.aicheckword_project_id && el("dg_project_id")) {
      if (String(el("dg_project_id").value || "") === String(pf.aicheckword_project_id)) setPrefillBadge("project", true);
    }
    (b.booleanOptions || []).forEach(function (row) {
      var sid = null;
      var badge = null;
      if (row.id === "inplace_patch") {
        sid = "dg_inplace";
        badge = "inplace";
      } else if (row.id === "multi_base_auto_route") {
        sid = "dg_multi_route";
        badge = "multi_route";
      } else if (row.id === "docx_track_changes") {
        sid = "dg_docx_track";
        badge = "track";
      } else if (row.id === "save_as_case") {
        sid = "dg_save_case";
        badge = "save_case";
      }
      if (!sid || !badge) return;
      var sel = el(sid);
      if (!sel) return;
      var def = !!row.default;
      var want = def ? "1" : "0";
      if (String(sel.value) === want) setPrefillBadge(badge, true);
    });
  }

  function applyProjectModeLabels() {
    var pm = el("dg_project_mode");
    if (!pm) return;
    for (var i = 0; i < pm.options.length; i++) {
      if (pm.options[i].value === "new") {
        pm.options[i].text = dgUserText("从页面1已有项目新建", "从任务列表已有项目新建");
      } else if (pm.options[i].value === "existing") {
        pm.options[i].text = dgUserText("使用已有项目（aicheckword，不新建）", "使用已有项目（不新建）");
      }
    }
  }

  function updatePage1AcwLinkedLabel() {
    var lab = el("dg_page1_acw_linked");
    if (!lab) return;
    if (_dgLinkedAcwProjectId > 0) {
      lab.textContent = dgUserText(
        "已关联 aicheckword 项目 ID：" + _dgLinkedAcwProjectId,
        "已关联专属项目 ID：" + _dgLinkedAcwProjectId
      );
      lab.classList.remove("text-muted");
      lab.classList.add("text-success");
    } else {
      lab.textContent = "";
      lab.classList.remove("text-success");
      lab.classList.add("text-muted");
    }
  }

  function updatePage1CreateBtnState() {
    var btn = el("dg_btn_open_acw_project_modal");
    var sel = el("dg_page1_project_id");
    if (!btn || !sel) return;
    btn.disabled = !(String(sel.value || "").trim());
  }

  function fillAcwModalSelect(selectId, options, preferred) {
    var sel = el(selectId);
    if (!sel) return;
    var opts = Array.isArray(options) ? options.slice() : [];
    sel.innerHTML = "";
    if (!opts.length) {
      var o0 = document.createElement("option");
      o0.value = "";
      o0.textContent = "（无可选项）";
      sel.appendChild(o0);
      return;
    }
    opts.forEach(function (v) {
      var s = String(v || "").trim();
      if (!s) return;
      var o = document.createElement("option");
      o.value = s;
      o.textContent = s;
      sel.appendChild(o);
    });
    var pref = String(preferred || "").trim();
    if (pref && opts.indexOf(pref) >= 0) sel.value = pref;
    else if (opts.length) sel.selectedIndex = 0;
  }

  function ensureAcwMetaFields(forceReload) {
    if (_dgAcwMetaFields && !forceReload) return Promise.resolve(_dgAcwMetaFields);
    if (forceReload) _dgAcwMetaFields = null;
    var collEl = el("dg_collection");
    var orgEl = el("dg_organization");
    var coll = (collEl && collEl.value ? collEl.value.trim() : "") || "regulations";
    var orgId = orgEl && orgEl.value ? String(orgEl.value).trim() : "";
    var url =
      "/draft-gen/api/acw-project-form-options?collection=" + encodeURIComponent(coll);
    if (orgId) url += "&organizationId=" + encodeURIComponent(orgId);
    return api(url, { method: "GET" }).then(function (x) {
      var j = x.json || {};
      if (x.ok && j.fields) {
        _dgAcwMetaFields = j.fields;
      } else {
        _dgAcwMetaFields = null;
      }
      return _dgAcwMetaFields;
    });
  }

  function loadPage1ProjectsForDraft() {
    var sel = el("dg_page1_project_id");
    if (!sel) return Promise.resolve();
    return api("/api/projects", { method: "GET" }).then(function (x) {
      if (!x.ok) {
        sel.innerHTML = '<option value="">（加载失败）</option>';
        return;
      }
      var rows = Array.isArray(x.json) ? x.json : [];
      _dgPage1ProjectsCache = rows;
      sel.innerHTML = '<option value="">' + dgUserText("（请选择页面1项目）", "（请选择项目）") + '</option>';
      rows.forEach(function (p) {
        var id = String(p.id || "").trim();
        if (!id) return;
        var o = document.createElement("option");
        o.value = id;
        var label = (p.name || id) + (p.registeredCountry ? " · " + p.registeredCountry : "");
        o.textContent = label;
        sel.appendChild(o);
      });
      applySelectSearchFilter("dg_page1_project_id");
      updatePage1CreateBtnState();
    });
  }

  function showAcwModalMsg(text, isErr) {
    var box = el("dg_acw_modal_msg");
    if (!box) return;
    if (!text) {
      box.classList.add("d-none");
      box.textContent = "";
      return;
    }
    box.textContent = text;
    box.classList.remove("d-none", "alert-danger", "alert-info");
    box.classList.add(isErr ? "alert-danger" : "alert-info");
  }

  function openAcwProjectModal() {
    var page1Id = String((el("dg_page1_project_id") && el("dg_page1_project_id").value) || "").trim();
    if (!page1Id) {
      showMsg(dgUserText("请先选择页面1已有项目", "请先选择任务列表中的项目"), true);
      return;
    }
    showAcwModalMsg("", false);
    var collEl = el("dg_collection");
    var orgEl = el("dg_organization");
    var coll = (collEl && collEl.value ? collEl.value.trim() : "") || "regulations";
    var orgId = orgEl && orgEl.value ? String(orgEl.value).trim() : "";
    var prefillUrl =
      "/draft-gen/api/page1-projects/" +
      encodeURIComponent(page1Id) +
      "/aicheckword-prefill?collection=" +
      encodeURIComponent(coll);
    if (orgId) prefillUrl += "&organizationId=" + encodeURIComponent(orgId);
    Promise.all([
      ensureAcwMetaFields(true),
      api(prefillUrl, { method: "GET" }),
    ]).then(function (parts) {
      var meta = parts[0] || {};
      var pre = parts[1];
      if (!pre.ok || !pre.json || !pre.json.data) {
        var em = (pre.json && pre.json.message) || "加载预填失败";
        showMsg(em, true);
        return;
      }
      var d = pre.json.data;
      if (el("dg_acw_name")) el("dg_acw_name").value = d.name || "";
      if (el("dg_acw_project_code")) el("dg_acw_project_code").value = d.project_code || "";
      if (el("dg_acw_name_en")) el("dg_acw_name_en").value = d.name_en || "";
      if (el("dg_acw_product_name")) el("dg_acw_product_name").value = d.product_name || "";
      if (el("dg_acw_product_name_en")) el("dg_acw_product_name_en").value = d.product_name_en || "";
      if (el("dg_acw_model")) el("dg_acw_model").value = d.model || "";
      if (el("dg_acw_model_en")) el("dg_acw_model_en").value = d.model_en || "";
      if (el("dg_acw_registration_country_en")) el("dg_acw_registration_country_en").value = d.registration_country_en || "";
      if (el("dg_acw_scope")) el("dg_acw_scope").value = d.scope_of_application || "";
      fillAcwModalSelect(
        "dg_acw_registration_country",
        (meta.registration_country && meta.registration_country.options) || [],
        d.registration_country
      );
      fillAcwModalSelect(
        "dg_acw_registration_type",
        (meta.registration_type && meta.registration_type.options) || [],
        d.registration_type
      );
      fillAcwModalSelect(
        "dg_acw_registration_component",
        (meta.registration_component && meta.registration_component.options) || [],
        d.registration_component
      );
      fillAcwModalSelect(
        "dg_acw_project_form",
        (meta.project_form && meta.project_form.options) || [],
        d.project_form || "Web"
      );
      var countryOpts = (meta.registration_country && meta.registration_country.options) || [];
      if (!countryOpts.length) {
        showAcwModalMsg(
          dgUserText(
            "未能加载注册国家/类别等选项，请检查 aicheckword 知识库或 collection 配置。",
            "未能加载注册国家/类别等选项，请刷新列表或联系管理员检查知识库配置。"
          ),
          true
        );
      }
      var modalEl = el("dgAcwProjectModal");
      if (!modalEl || typeof bootstrap === "undefined") return;
      if (!_dgAcwModalInstance) _dgAcwModalInstance = new bootstrap.Modal(modalEl);
      _dgAcwModalInstance.show();
    });
  }

  function collectAcwModalBody() {
    var page1Id = String((el("dg_page1_project_id") && el("dg_page1_project_id").value) || "").trim();
    var collEl = el("dg_collection");
    var orgEl = el("dg_organization");
    return {
      page1ProjectId: page1Id,
      collection: (collEl && collEl.value ? collEl.value.trim() : "") || "regulations",
      organizationId: orgEl && orgEl.value ? String(orgEl.value).trim() : null,
      name: String((el("dg_acw_name") && el("dg_acw_name").value) || "").trim(),
      project_code: String((el("dg_acw_project_code") && el("dg_acw_project_code").value) || "").trim(),
      name_en: String((el("dg_acw_name_en") && el("dg_acw_name_en").value) || "").trim(),
      product_name: String((el("dg_acw_product_name") && el("dg_acw_product_name").value) || "").trim(),
      product_name_en: String((el("dg_acw_product_name_en") && el("dg_acw_product_name_en").value) || "").trim(),
      model: String((el("dg_acw_model") && el("dg_acw_model").value) || "").trim(),
      model_en: String((el("dg_acw_model_en") && el("dg_acw_model_en").value) || "").trim(),
      registration_country: String((el("dg_acw_registration_country") && el("dg_acw_registration_country").value) || "").trim(),
      registration_country_en: String((el("dg_acw_registration_country_en") && el("dg_acw_registration_country_en").value) || "").trim(),
      registration_type: String((el("dg_acw_registration_type") && el("dg_acw_registration_type").value) || "").trim(),
      registration_component: String((el("dg_acw_registration_component") && el("dg_acw_registration_component").value) || "").trim(),
      project_form: String((el("dg_acw_project_form") && el("dg_acw_project_form").value) || "").trim(),
      scope_of_application: String((el("dg_acw_scope") && el("dg_acw_scope").value) || "").trim(),
    };
  }

  var ACW_MODAL_REQUIRED_FIELDS = [
    ["name", "项目名称"],
    ["project_code", "项目编号"],
    ["name_en", "项目名称（英文）"],
    ["product_name", "产品名称"],
    ["product_name_en", "产品名称（英文）"],
    ["model", "型号"],
    ["model_en", "型号（英文）"],
    ["registration_country", "注册国家"],
    ["registration_country_en", "注册国家（英文）"],
    ["registration_type", "注册类别"],
    ["registration_component", "注册组成"],
    ["project_form", "项目形态"],
    ["scope_of_application", "产品适用范围"],
  ];

  function validateAcwModalBody(body) {
    var missing = [];
    ACW_MODAL_REQUIRED_FIELDS.forEach(function (pair) {
      var key = pair[0];
      var label = pair[1];
      if (!String(body[key] || "").trim()) missing.push(label);
    });
    if (!missing.length) return "";
    return (
      "请填写完整项目信息（尚缺：" +
      missing.join("、") +
      "）。信息齐全有助于提升初稿质量；" +
      dgUserText(
        "也可联系超级管理员在 aicheckword 中代为新建专属项目。",
        "也可联系超级管理员代为新建专属项目。"
      )
    );
  }

  function saveAcwProjectFromModal() {
    var body = collectAcwModalBody();
    var valErr = validateAcwModalBody(body);
    if (valErr) {
      showAcwModalMsg(valErr, true);
      return;
    }
    if (!body.name) {
      showAcwModalMsg(dgUserText("该页面1 项目尚未填写项目编号，请先到页面1 任务列表中填写后再试。", "该项目尚未填写项目编号，请先在任务列表中填写后再试。"), true);
      return;
    }
    var btn = el("dg_btn_save_acw_project");
    if (btn) btn.disabled = true;
    showAcwModalMsg("正在保存…", false);
    api("/draft-gen/api/aicheckword-projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (x) {
      if (btn) btn.disabled = false;
      if (!x.ok || !x.json || !x.json.ok) {
        showAcwModalMsg((x.json && x.json.message) || "保存失败", true);
        return;
      }
      var pid = parseInt(String(x.json.projectId || (x.json.data && x.json.data.projectId) || 0), 10) || 0;
      if (pid <= 0) {
        showAcwModalMsg(dgUserText("上游未返回 projectId", "保存失败：未返回项目编号"), true);
        return;
      }
      _dgLinkedAcwProjectId = pid;
      updatePage1AcwLinkedLabel();
      showAcwModalMsg(
        dgUserText("已创建 aicheckword 专属项目 ID：" + pid, "已创建专属项目 ID：" + pid),
        false
      );
      if (_dgAcwModalInstance) _dgAcwModalInstance.hide();
      showMsg(
        dgUserText(
          "已在 aicheckword 创建专属项目（ID " + pid + "），提交初稿时将使用该 project_id。",
          "已创建专属项目（ID " + pid + "），提交初稿时将自动关联该项目。"
        ),
        false
      );
      return loadDraftBootstrap();
    });
  }

  function syncProjectUi() {
    const pm = el("dg_project_mode");
    const wrap = el("dg_project_pick_wrap");
    const wrapPage1 = el("dg_page1_project_wrap");
    if (!pm) return;
    const isExisting = pm.value === "existing";
    const isNewFromPage1 = pm.value === "new";
    if (wrap) wrap.style.display = isExisting ? "" : "none";
    if (wrapPage1) wrapPage1.style.display = isNewFromPage1 ? "" : "none";
    if (isNewFromPage1) {
      loadPage1ProjectsForDraft();
    }
    var defSave = pm.value === "new";
    fillYesNo("dg_save_case", defSave);
  }

  function loadDraftBootstrap() {
    beginDraftBootstrapLoading();
    clearAllPrefillBadges();
    _dgAuthorRoleUserTouched = false;
    __page2DidTemplatePrefill = false;
    const collEl = el("dg_collection");
    const orgEl = el("dg_organization");
    const pf = getPage2Prefill();
    let orgId = orgEl && orgEl.value ? String(orgEl.value).trim() : "";
    let coll = (collEl && collEl.value) ? collEl.value.trim() : "";
    if (!coll && pf && pf.collection) coll = pf.collection;
    if (!coll) coll = "regulations";
    const bcEl = el("dg_base_case");
    let bcRaw = bcEl && bcEl.value ? String(bcEl.value).trim() : "";
    if (!bcRaw && pf && pf.base_case_id) bcRaw = String(pf.base_case_id);
    let path = "/draft-gen/api/draft-bootstrap?collection=" + encodeURIComponent(coll || "regulations");
    if (orgId) path += "&organizationId=" + encodeURIComponent(orgId);
    if (bcRaw) path += "&base_case_id=" + encodeURIComponent(bcRaw);
    return loadIso13485DocNamePairs()
      .then(function () {
        return api(path, { method: "GET" });
      })
      .then(function (x) {
      const ta = el("dg_meta_preview");
      if (!x.ok) {
        if (ta) ta.value = JSON.stringify(x.json, null, 2);
        showMsg(x.json.message || "加载生成选项失败", true);
        return;
      }
      const b = x.json;
      var routeUi = "default";
      if (pf && pf.country) routeUi = classifyRegRouteFromAiwordCountry(pf.country);
      b.cases = sortCasesByDocumentLanguageRoute(b.cases || [], routeUi);
      lastBootstrap = b;
      if (ta) ta.value = JSON.stringify(b.upstreamBody != null ? b.upstreamBody : b, null, 2);
      if (!b.metaOk && b.metaError) {
        showMsg(
          dgUserText(
            "上游列表：" + b.metaError + "（下拉可能为空，请检查 aicheckword 与知识库）",
            "加载选项失败：" + b.metaError + "（下拉可能为空，请检查知识库配置或联系管理员）"
          ),
          true
        );
      }

      var IP = window.IntegrationPrefill;
      if (orgEl && IP && IP.fillOrganizationSelect) {
        window["__integrationOrgs_dg"] = b.organizations || [];
        var pickOrg = orgId || b.activeOrganizationId;
        IP.fillOrganizationSelect("dg", b.organizations || [], pickOrg);
        if (IP.wireOrganizationSelect) {
          IP.wireOrganizationSelect("dg", {
            root: (window.__SCRIPT_ROOT__ || "").replace(/\/+$/, ""),
            orgContextRoot: ((window.__SCRIPT_ROOT__ || "").replace(/\/+$/, "") + "/audit"),
            onOrganizationChange: function () {
              if (el("dg_base_case")) el("dg_base_case").value = "";
              loadDraftBootstrap();
            },
          });
        }
        if (collEl) collEl.value = IP.syncCollectionFromOrganization
          ? IP.syncCollectionFromOrganization("dg", el("dg_organization").value, b.organizations)
          : (b.collection || b.activeKnowledgeCollection || coll);
        var disp = el("dg_collection_display");
        if (disp && collEl) disp.textContent = collEl.value;
      } else if (collEl && collEl.tagName === "SELECT") {
        fillSelectThenCache("dg_collection", b.collections || [], "id", "label", null);
        if (collEl) {
          var colIds = (b.collections || []).map(function (c) { return String(c.id); });
          if (colIds.indexOf(coll) >= 0) collEl.value = coll;
          else if (pf && pf.collection && colIds.indexOf(pf.collection) >= 0) collEl.value = pf.collection;
          else if (colIds.indexOf("regulations") >= 0) collEl.value = "regulations";
        }
      } else if (collEl) {
        collEl.value = b.collection || b.activeKnowledgeCollection || coll;
        var disp2 = el("dg_collection_display");
        if (disp2) disp2.textContent = collEl.value;
      }

      fillSelectThenCache("dg_base_case", b.cases || [], "id", "label", { value: "", label: "（请选择模板项目案例）" });
      if (bcRaw && bcEl) {
        const ids = (b.cases || []).map(function (c) { return String(c.id); });
        if (ids.indexOf(bcRaw) >= 0) bcEl.value = bcRaw;
      }

      fillSelect("dg_template_scope", b.templateScopeModes || [], "value", "label", null);
      rebuildTemplateCheckboxes(b.templates || [], (el("dg_template_scope") && el("dg_template_scope").value) === "all");
      syncTemplateFilesUiDisabled();

      fillSelectThenCache("dg_doc_lang", b.documentLanguages || [], "value", "label", null);
      (function () {
        var dl = el("dg_doc_lang");
        if (!dl || !dl.options.length) return;
        var vals = Array.prototype.map.call(dl.options, function (o) { return o.value; });
        if (vals.indexOf(dl.value) < 0) {
          if (vals.indexOf("zh") >= 0) dl.value = "zh";
          else dl.selectedIndex = 0;
        }
      })();

      fillSelectThenCache("dg_strategy", b.draftStrategies || [], "value", "label", null);
      fillSelectThenCache("dg_author_role", b.authorRoles || [], "value", "label", null);
      fillSelect("dg_project_mode", b.projectModes || [], "value", "label", null);
      applyProjectModeLabels();
      fillSelectThenCache("dg_project_id", b.projects || [], "id", "label", { value: "", label: "（不指定具体项目编号）" });

      applyBooleanOptionLabels(b.booleanOptions || []);
      var bools = b.booleanOptions || [];
      bools.forEach(function (row) {
        var def = !!row.default;
        if (row.id === "inplace_patch") fillYesNo("dg_inplace", def);
        if (row.id === "multi_base_auto_route") fillYesNo("dg_multi_route", def);
        if (row.id === "docx_track_changes") fillYesNo("dg_docx_track", def);
      });
      syncProjectUi();
      [
        "dg_base_case_filter",
        "dg_doc_lang_filter",
        "dg_strategy_filter",
        "dg_author_role_filter",
        "dg_project_id_filter",
        "dg_template_filter",
      ].forEach(function (fid) {
        var inp = el(fid);
        if (inp) inp.value = "";
      });
      ["dg_base_case", "dg_doc_lang", "dg_strategy", "dg_author_role", "dg_project_id"].forEach(
        function (sid) {
          applySelectSearchFilter(sid);
        }
      );
      applyTemplateCheckboxFilter();
      if (maybeApplyPage2PrefillAfterBootstrap(b)) {
        return loadDraftBootstrap();
      }
      applyAuthorRoleSuggestionAfterBootstrap(b);
      updateDefaultFilledBadges(b, getPage2Prefill());
    })
      .catch(function () {
        showMsg("加载生成选项失败（网络或服务异常），请稍后重试或点击「刷新列表」。", true);
      })
      .finally(function () {
        endDraftBootstrapLoading();
      });
  }

  function loadLlmSettings() {
    return api("/draft-gen/api/llm-settings", { method: "GET" }).then(function (x) {
      if (!x.ok) {
        showMsg(x.json.message || "加载失败", true);
        return;
      }
      const d = x.json;
      lastHasLlmKey = !!d.hasApiKey;
      lastPersonalKeysOnly = d.personalKeysOnly !== false;
      lastHasApiKeyByProvider = d.hasApiKeyByProvider && typeof d.hasApiKeyByProvider === "object"
        ? d.hasApiKeyByProvider
        : { deepseek: !!d.hasApiKey, cursor: false, tongyi: false };
      lastApiBaseByProvider = mergeProviderStringMap(d.apiBaseUrlByProvider);
      if (!d.apiBaseUrlByProvider && d.apiBaseUrl) {
        var pvb = d.provider || "deepseek";
        lastApiBaseByProvider[pvb] = String(d.apiBaseUrl || "");
      }
      lastLlmModelByProvider = mergeProviderStringMap(d.llmModelByProvider);
      if (!d.llmModelByProvider && d.llmModel) {
        var pvm = d.provider || "deepseek";
        lastLlmModelByProvider[pvm] = String(d.llmModel || "");
      }
      if (d.allowedProviders && d.allowedProviders.length) {
        rebuildProviderSelect(d.allowedProviders);
      }
      el("dg_provider").value = d.provider || "deepseek";
      var pvUse = el("dg_provider").value || "deepseek";
      applyLlmExtrasFromMaps(pvUse);
      lastLlmProviderSelection = pvUse;
      showInteropInfo(d);
      var rq = document.querySelector("#dg_api_key_block .dg-req-llm");
      if (rq) {
        if (lastPersonalKeysOnly) rq.classList.remove("d-none");
        else rq.classList.add("d-none");
      }
      syncLlmProviderUi();
      if (d.hasEncryptedBlobByProvider && d.keyDecryptOkByProvider) {
        var provWarn = el("dg_provider").value || "deepseek";
        var hasBlob = !!d.hasEncryptedBlobByProvider[provWarn];
        var decryptOk = !!d.keyDecryptOkByProvider[provWarn];
        if (hasBlob && !decryptOk) {
          showMsg(
            "检测到已保存的 Key 无法解密（常见原因：系统 SECRET_KEY 曾变更）。请重新粘贴 Key 并保存。",
            true
          );
        }
      }
    });
  }

  function saveLlmSettings() {
    const prov = el("dg_provider").value.trim();
    stashLlmExtrasForProvider(prov);
    const body = {
      provider: prov,
      apiKey: el("dg_api_key").value.trim(),
      apiBaseUrl: el("dg_api_base_url").value.trim(),
      llmModel: el("dg_llm_model").value.trim(),
    };
    api("/draft-gen/api/llm-settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (x) {
      if (!x.ok) {
        showMsg(x.json.message || "保存失败", true);
        return;
      }
      el("dg_api_key").value = "";
      showMsg("已保存个人 LLM 设置（初稿/审核/翻译/审核后修改共用，API Key 已加密落库）", false);
      loadLlmSettings();
    });
  }

  function testLlmSettings() {
    const prov = el("dg_provider").value.trim();
    stashLlmExtrasForProvider(prov);
    const body = {
      provider: prov,
      testOnly: true,
      apiKey: el("dg_api_key").value.trim(),
      apiBaseUrl: el("dg_api_base_url").value.trim(),
      llmModel: el("dg_llm_model").value.trim(),
    };
    api("/draft-gen/api/llm-settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (x) {
      if (!x.ok || x.json.ok === false) {
        showMsg((x.json && x.json.message) || "Key 测试失败", true);
        return;
      }
      showMsg((x.json && x.json.message) || "Key 验证通过", false);
    });
  }

  function selectedTemplateNames() {
    const box = el("dg_template_files_box");
    if (!box) return [];
    const out = [];
    box.querySelectorAll('input[type="checkbox"][data-template-name]:checked').forEach(function (inp) {
      const v = (inp.getAttribute("data-template-name") || inp.value || "").trim();
      if (v) out.push(v);
    });
    return out;
  }

  /** 勾选列表：已选项移到容器顶部（非下拉框，需 DOM 重排才明显） */
  function reorderTemplateCheckboxesSelectedFirst() {
    var box = el("dg_template_files_box");
    if (!box) return;
    var wraps = Array.prototype.slice.call(box.querySelectorAll(":scope > .form-check"));
    if (wraps.length < 2) return;
    var checked = [];
    var unchecked = [];
    var i;
    for (i = 0; i < wraps.length; i++) {
      var w = wraps[i];
      var inp = w.querySelector('input[type="checkbox"][data-template-name]');
      if (!inp) continue;
      if (inp.checked) checked.push(w);
      else unchecked.push(w);
    }
    for (i = 0; i < checked.length; i++) box.appendChild(checked[i]);
    for (i = 0; i < unchecked.length; i++) box.appendChild(unchecked[i]);
    applyTemplateCheckboxFilter();
  }

  function updateTemplateSelectionSummary() {
    var outEl = el("dg_template_selection_summary");
    if (!outEl) return;
    var scope = (el("dg_template_scope") && el("dg_template_scope").value) || "selected";
    var tplList =
      lastBootstrap && lastBootstrap.templates
        ? lastBootstrap.templates
            .map(function (t) {
              return String(t.id || "").trim();
            })
            .filter(Boolean)
        : [];
    if (scope === "all") {
      outEl.textContent = tplList.length
        ? "当前范围：将生成该案例下全部模板文件（共 " + tplList.length + " 个），下方勾选已禁用。"
        : "当前范围：全部模板；本案例下暂无模板文件名。";
      return;
    }
    var names = selectedTemplateNames();
    if (!names.length) {
      outEl.textContent =
        "当前未勾选任何模板文件。勾选后，该项会自动移到列表上方，并在此处汇总已选文件名。";
      return;
    }
    var maxShow = 8;
    var shown = names.slice(0, maxShow);
    var more = names.length > maxShow ? " 等共 " + names.length + " 个" : "";
    outEl.textContent =
      "当前已选择：" + shown.map(function (n) { return "「" + n + "」"; }).join("、") + more + "。";
  }

  function buildPayload() {
    const coll = el("dg_collection").value.trim() || "regulations";
    const orgId = (window.IntegrationPrefill && window.IntegrationPrefill.readOrganizationId
      ? window.IntegrationPrefill.readOrganizationId("dg")
      : (el("dg_organization") && el("dg_organization").value) || "").trim();
    const bc = parseInt(el("dg_base_case").value.trim() || "0", 10) || 0;
    const scope = (el("dg_template_scope") && el("dg_template_scope").value) || "selected";
    const tplList = (lastBootstrap && lastBootstrap.templates) ? lastBootstrap.templates.map(function (t) { return t.id; }) : [];

    let names = [];
    if (scope === "all") {
      names = tplList.slice();
    } else {
      names = selectedTemplateNames();
    }
    if (scope === "selected" && !names.length && tplList.length) {
      throw new Error("请至少勾选一个模板文件，或改为「该案例下全部模板文件」。");
    }

    var providerVal = ((el("dg_provider") && el("dg_provider").value) || "").trim();
    const payload = {
      collection: coll,
      organizationId: orgId || null,
      base_case_id: bc,
      provider: providerVal || null,
      document_language: el("dg_doc_lang").value,
      inplace_patch: el("dg_inplace").value === "1",
      save_as_case: el("dg_save_case").value === "1",
      multi_base_auto_route: el("dg_multi_route").value === "1",
      draft_strategy: el("dg_strategy").value.trim() || "change",
      docx_track_changes: el("dg_docx_track").value === "1",
      persist_project_fields: false,
    };
    const ar = el("dg_author_role").value;
    if (ar) payload.author_role = ar;

    const mode = el("dg_project_mode").value;
    const pid = el("dg_project_id").value.trim();
    if (mode === "existing" && pid) {
      payload.project_id = parseInt(pid, 10);
    } else if (mode === "new") {
      if (!_dgLinkedAcwProjectId) {
        throw new Error(
          dgUserText(
            "请先从页面1已有项目新建 aicheckword 专属项目",
            "请先从页面1已有项目新建专属项目"
          )
        );
      }
      payload.project_id = _dgLinkedAcwProjectId;
    }

    if (names.length) payload.template_file_names = names;

    const extra = (el("dg_payload_extra").value || "").trim();
    if (extra) {
      try {
        const o = JSON.parse(extra);
        if (o && typeof o === "object") {
          Object.assign(payload, o);
        }
      } catch (e) {
        throw new Error("附加 JSON 无效: " + e);
      }
    }
    var uapEl = el("dg_user_prompt_append");
    var uap = uapEl ? String(uapEl.value || "").trim() : "";
    if (uap) payload.user_prompt_append = uap.slice(0, 8000);
    return payload;
  }

  function pollJob(localId, onDone) {
    // 与 webapp/draft_generation_routes._DRAFT_READ_TIMEOUT_MAX_SECONDS（72h）对齐：按墙钟而非 tick 数，
    // 避免旧逻辑 2400*800ms≈32min 远短于服务端可配置的上游读超时。
    var pollDeadlineMs = Date.now() + 72 * 3600 * 1000;
    var pollN = 0;
    draftProgressSetVisible(true);
    draftProgressSetHeadline(
      dgUserText(
        "正在生成（后台轮询上游，与 aicheckword 初稿页进度条一致）",
        "正在生成，请稍候…"
      )
    );
    draftProgressSetRunningStyle(true);
    draftProgressUpdate(0.06, dgUserText("任务已提交，等待上游执行…", "任务已提交，请稍候…"), "本地任务 " + localId);
    function tick() {
      if (Date.now() > pollDeadlineMs) {
        draftProgressSetRunningStyle(false);
        draftProgressSetTerminal(false);
        draftProgressSetHeadline("等待超时，已停止轮询");
        draftProgressUpdate(1, "轮询超时（已超过 72 小时）", "本地任务 " + localId);
        onDone(new Error("轮询超时（已超过 72 小时）"));
        return;
      }
      api("/draft-gen/api/jobs/" + encodeURIComponent(localId) + "/status", { method: "GET" }).then(function (x) {
        var j = x.json && typeof x.json === "object" ? x.json : {};
        if (!x.ok) {
          var em = j.message || j.detail || ("HTTP " + x.status);
          draftProgressSetRunningStyle(false);
          draftProgressSetTerminal(false);
          draftProgressSetHeadline("状态查询失败");
          draftProgressUpdate(0.35, em || "状态查询失败", "本地任务 " + localId);
          onDone(new Error(em));
          return;
        }
        const d = x.json;
        const st = (d.status || "").toLowerCase();
        var pr = d.progress;
        var pnum = pr != null ? parseFloat(pr) : NaN;
        if (isNaN(pnum)) pnum = st === "succeeded" ? 1 : st === "failed" ? 1 : 0.12;
        var msg = (d.message || "").trim() || (st ? "状态：" + dgStatusZh(st) : "处理中…");
        var up = d.upstreamJobId || d.upstream_job_id;
        draftProgressUpdate(
          pnum,
          msg,
          dgUserText("本地 " + localId + (up ? " · 上游 " + up : ""), "本地 " + localId + (up ? " · 任务 " + up : ""))
        );
        if (st === "succeeded" || st === "failed") {
          draftProgressSetRunningStyle(false);
          draftProgressSetTerminal(st === "succeeded");
          draftProgressSetHeadline(st === "succeeded" ? "生成已完成" : "生成失败");
          var errTail = d.error || d.errorSummary || "";
          draftProgressUpdate(
            st === "succeeded" ? 1 : pnum,
            st === "succeeded" ? "生成完成，可下载 ZIP" : msg + (errTail ? " · " + String(errTail).slice(0, 200) : ""),
            dgUserText("本地 " + localId + (up ? " · 上游 " + up : ""), "本地 " + localId + (up ? " · 任务 " + up : ""))
          );
          onDone(null, d);
          return;
        }
        // 任务进行中：适度拉长轮询间隔，减轻 aiword/aicheckword 日志与连接压力（非异常）。
        var delayMs = pollN < 45 ? 1200 : pollN < 150 ? 2800 : 4500;
        pollN += 1;
        setTimeout(tick, delayMs);
      }).catch(function (e) {
        draftProgressSetRunningStyle(false);
        draftProgressSetTerminal(false);
        draftProgressSetHeadline("轮询异常中断");
        draftProgressUpdate(
          0.35,
          String((e && e.message) || e || "网络或脚本异常"),
          "本地任务 " + localId
        );
        onDone(e);
      });
    }
    tick();
  }

  function postDraftJob(payload) {
    if (_dgBaseUploadId && String(_dgBaseUploadId).trim()) {
      payload.base_upload_id = String(_dgBaseUploadId).trim();
    }
    const fd = new FormData();
    fd.append("payload", JSON.stringify(payload));
    _dgInputFilesAccum.forEach(function (f) {
      fd.append("input_files", f, f.name);
    });
    _dgBaseFilesAccum.forEach(function (f) {
      fd.append("base_files", f, f.name);
    });
    fd.append("integration_scope", dgIntegrationScopeFromLocation());
    var submitBtn = el("dg_btn_submit");
    if (submitBtn) submitBtn.disabled = true;
    function releaseSubmitBtn() {
      if (submitBtn) submitBtn.disabled = false;
    }
    showMsg("正在提交…", false);
    draftProgressSetVisible(true);
    draftProgressSetHeadline(dgUserText("正在上传并提交到上游…", "正在上传并提交…"));
    draftProgressResetBarStyle();
    draftProgressSetRunningStyle(true);
    draftProgressUpdate(0.03, dgUserText("正在上传文件并提交到上游…", "正在上传文件并提交…"), "");
    fetch(root + "/draft-gen/api/jobs", { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) {
        return r.json().then(function (j) { return { ok: r.ok, json: j }; });
      })
      .then(function (x) {
        if (!x.ok || !x.json.ok) {
          draftProgressSetRunningStyle(false);
          draftProgressSetTerminal(false);
          draftProgressSetHeadline("提交未完成");
          var failMsg = (x.json && x.json.message) || "提交失败";
          draftProgressUpdate(0, failMsg, "");
          showMsg(failMsg, true);
          releaseSubmitBtn();
          return;
        }
        const localId = x.json.localJobId;
        el("dg_local_job_id").value = localId;
        // 勿在 POST 成功后立刻清空文件列表：若上游随后失败，用户再次提交会因无输入文件而直接 return，
        // 表现为「按钮没反应」。仅在生成成功后再清空，失败/超时时保留文件便于重试。
        draftProgressSetHeadline(
      dgUserText(
        "正在生成（后台轮询上游，与 aicheckword 初稿页进度条一致）",
        "正在生成，请稍候…"
      )
    );
        showMsg("已提交，任务号 " + localId + "，轮询中…", false);
        var pr0 = x.json.progress != null ? parseFloat(x.json.progress) : 0.08;
        if (!isNaN(pr0)) draftProgressUpdate(pr0, dgUserText("已提交上游，正在排队/执行…", "正在排队/执行…"), "本地任务 " + localId);
        pollJob(localId, function (err, finalJson) {
          releaseSubmitBtn();
          if (err) {
            showMsg(String(err.message || err), true);
            loadJobList();
            return;
          }
          const st = (finalJson.status || "").toLowerCase();
          if (st === "succeeded") {
            showMsg(
              "生成成功，可下载 ZIP。可修改选项后再次点击「提交生成」（已保留本次上传的文件列表）。",
              false
            );
            warmDraftZipCache(localId).finally(function () {
              var db = el("dg_btn_download");
              if (db) db.disabled = false;
            });
          } else {
            var failDetail = finalJson.message || finalJson.error || finalJson.errorSummary || "";
            showMsg("任务结束: " + dgStatusZh(st) + (failDetail ? " · " + failDetail : ""), true);
          }
          loadJobList();
        });
      })
      .catch(function (e) {
        draftProgressSetRunningStyle(false);
        draftProgressSetTerminal(false);
        draftProgressSetHeadline("提交异常中断");
        draftProgressUpdate(0, String(e), "");
        showMsg(String(e), true);
        releaseSubmitBtn();
      });
  }

  function submitJob() {
    let payload;
    try {
      payload = buildPayload();
    } catch (e) {
      showMsg(String(e.message || e), true);
      return;
    }
    if (!payload.base_case_id) {
      showMsg("请选择「模板项目案例」后再提交。", true);
      return;
    }
    var projMode = el("dg_project_mode") && el("dg_project_mode").value;
    if (projMode === "new" && !_dgLinkedAcwProjectId) {
      showMsg(
        dgUserText(
          "项目模式为「从页面1已有项目新建」时，须先选择页面1项目并点击「新建项目」保存到 aicheckword。",
          "项目模式为「从页面1已有项目新建」时，须先选择页面1项目并点击「新建项目」完成保存。"
        ),
        true
      );
      return;
    }
    if (projMode === "existing") {
      var pidCheck = parseInt(String((el("dg_project_id") && el("dg_project_id").value) || "").trim(), 10) || 0;
      if (pidCheck <= 0) {
        showMsg(dgUserText("请选择 aicheckword 已有项目。", "请选择已有专属项目。"), true);
        return;
      }
    }
    if (!_dgInputFilesAccum.length) {
      showMsg(
        dgUserText(
          "请先添加至少一个输入/参考文件（与 aicheckword 一致；可多次点「选择文件」追加，或在对话框内 Ctrl/Shift 多选）。",
          "请先添加至少一个输入/参考文件（可多次点「选择文件」追加，或在对话框内 Ctrl/Shift 多选）。"
        ),
        true
      );
      var msgBox = el("dg_msg");
      if (msgBox && msgBox.scrollIntoView) {
        msgBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
      return;
    }
    var hasTaskBase = !!(_dgBaseUploadId && String(_dgBaseUploadId).trim());
    var hasUploadBase = _dgBaseFilesAccum.length > 0;
    if (hasTaskBase && hasUploadBase) {
      showMsg(dgUserText("Base 来源唯一：请在“页面2带入 Base”与“手动上传 Base”二选一。", "Base 来源唯一：请在“任务带入 Base”与“手动上传 Base”二选一。"), true);
      return;
    }
    var inplaceOn = el("dg_inplace") && el("dg_inplace").value === "1";
    var missingDisk = selectedTemplatesMissingDiskBase();
    if (inplaceOn && missingDisk.length && !hasTaskBase && !hasUploadBase) {
      var preview = missingDisk.slice(0, 6).map(function (n) { return "「" + n + "」"; }).join("、");
      var more = missingDisk.length > 6 ? " 等共 " + missingDisk.length + " 个" : "";
      showMsg(
        "所选模板在服务器上未找到案例/训练目录原件，请上传 Base：" + preview + more +
          "。Chroma 中的训练文本不能替代 Word/Excel 基底。",
        true
      );
      return;
    }
    var provUse = ((el("dg_provider") && el("dg_provider").value) || "").trim();
    var keyMap = lastHasApiKeyByProvider || {};
    if (
      lastPersonalKeysOnly &&
      provUse &&
      Object.prototype.hasOwnProperty.call(keyMap, provUse) &&
      !keyMap[provUse]
    ) {
      showMsg(
        "当前选择的是「" +
          provUse +
          "」，但该提供方尚未保存可用的 API Key。请填写 Key 并点「保存个人 LLM 设置」。",
        true
      );
      return;
    }
    if (!payload.input_vector_on_duplicate) {
      payload.input_vector_on_duplicate = "skip";
    }
    var pid = payload.project_id;
    if (pid && _dgInputFilesAccum.length) {
      var names = _dgInputFilesAccum.map(function (f) {
        return f.name || "file";
      });
      fetch(root + "/draft-gen/api/check-input-vector-duplicates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ project_id: pid, file_names: names }),
      })
        .then(function (r) {
          return r.json().then(function (j) {
            return { ok: r.ok, json: j };
          });
        })
        .then(function (x) {
          if (!x.ok || !x.json || x.json.ok === false) {
            var em =
              (x.json && (x.json.message || x.json.detail)) ||
              "检测参考文件是否已向量化失败";
            showMsg(em, true);
            return;
          }
          var dups = x.json.duplicates || [];
          if (dups.length) {
            var lines = dups.slice(0, 15).join("\n");
            if (dups.length > 15) lines += "\n…等 " + dups.length + " 个";
            var ask =
              "以下参考/输入文件在当前项目中已向量化：\n\n" +
              lines +
              "\n\n点击「确定」= 重新向量化并覆盖已有数据；\n点击「取消」= 不重复向量化，优先使用库内已有向量。";
            if (window.confirm(ask)) {
              payload.input_vector_on_duplicate = "overwrite";
            } else {
              payload.input_vector_on_duplicate = "skip";
            }
          }
          postDraftJob(payload);
        })
        .catch(function (e) {
          showMsg(String(e.message || e), true);
        });
      return;
    }
    postDraftJob(payload);
  }

  function downloadZipById(localId) {
    if (!localId) return Promise.resolve();
    var url = root + "/draft-gen/api/jobs/" + encodeURIComponent(localId) + "/download";
    return fetch(url, { method: "GET", credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) {
          return r.text().then(function (text) {
            var msg = "下载失败（HTTP " + r.status + "）";
            try {
              var j = JSON.parse(text);
              if (j && j.message) msg = j.message;
            } catch (e) {
              if (text && text.indexOf("Internal Server Error") >= 0) {
                msg = "下载失败：服务器内部错误。请从下方历史记录再次点击下载，或刷新页面后重试。";
              }
            }
            throw new Error(msg);
          });
        }
        return r.blob();
      })
      .then(function (blob) {
        var a = document.createElement("a");
        var objUrl = URL.createObjectURL(blob);
        a.href = objUrl;
        a.download = "draft_" + localId + ".zip";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(objUrl);
        showMsg("下载已开始", false);
        loadJobList();
      });
  }

  function warmDraftZipCache(localId) {
    if (!localId) return Promise.resolve();
    var url = root + "/draft-gen/api/jobs/" + encodeURIComponent(localId) + "/download";
    return fetch(url, { method: "GET", credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) return r.text().then(function () { return false; });
        return r.blob().then(function () { return true; });
      })
      .catch(function () { return false; })
      .then(function () { loadJobList(); });
  }

  function downloadZip() {
    const localId = el("dg_local_job_id").value.trim();
    if (!localId) return;
    showMsg("正在准备下载…", false);
    downloadZipById(localId).catch(function (e) {
      showMsg(String(e.message || e), true);
    });
  }

  function applyJobSnapshot(jobId) {
    if (!jobId) return;
    api("/draft-gen/api/jobs/" + encodeURIComponent(jobId) + "/snapshot", { method: "GET" }).then(function (x) {
      if (!x.ok || !x.json || !x.json.ok) {
        showMsg((x.json && x.json.message) || "加载快照失败", true);
        return;
      }
      var snap = x.json.snapshot || {};
      if (snap.base_case_id != null && el("dg_base_case")) el("dg_base_case").value = String(snap.base_case_id);
      if (snap.project_id != null && el("dg_project_id")) {
        el("dg_project_id").value = String(snap.project_id);
        if (el("dg_project_mode")) el("dg_project_mode").value = "existing";
      }
      if (snap.document_language && el("dg_doc_lang")) el("dg_doc_lang").value = snap.document_language;
      if (snap.collection && el("dg_collection")) el("dg_collection").value = snap.collection;
      if (snap.inplace_patch != null && el("dg_inplace")) el("dg_inplace").value = snap.inplace_patch ? "1" : "0";
      var tplNames = x.json.templateNames || snap.template_file_names || [];
      if (Array.isArray(tplNames) && tplNames.length) {
        if (el("dg_template_scope")) el("dg_template_scope").value = "selected";
        document.querySelectorAll('input[name="dg_tpl_cb"]').forEach(function (cb) {
          cb.checked = tplNames.indexOf(cb.value) >= 0;
        });
        applyTemplateCheckboxFilter();
        updateTemplateSelectionSummary();
      }
      var inNames = x.json.inputDisplayNames || [];
      showMsg(
        "已回填历史参数（案例/项目/模板等）。请重新选择输入文件"
          + (inNames.length ? "（上次：" + inNames.slice(0, 3).join("、") + (inNames.length > 3 ? "…" : "") + "）" : "")
          + " 后提交。",
        false
      );
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  function loadJobList() {
    return api("/draft-gen/api/jobs?page=" + encodeURIComponent(String(_dgJobsPage || 1)) + "&page_size=10&" + dgIntegrationScopeQuery(), { method: "GET" }).then(function (x) {
      const tb = el("dg_job_rows");
      if (!tb) return;
      if (!x.ok) {
        if (x.status === 401 && x.json && x.json.message) showMsg(x.json.message, true);
        return;
      }
      tb.innerHTML = "";
      (x.json.jobs || []).forEach(function (j) {
        const tr = document.createElement("tr");
        function tdText(t) {
          const td = document.createElement("td");
          td.appendChild(document.createTextNode(t != null ? String(t) : ""));
          tr.appendChild(td);
        }
        const st = (j.status || "").toLowerCase();
        tdText(j.createdAt || "");
        tdText(dgStatusZh(j.status));
        tdText((j.summaryLine || j.message || "").slice(0, 220));
        tdText(j.id || "");
        tdText(j.upstreamJobId || "");
        tdText(j.durationMs != null ? j.durationMs : "");
        const tdOp = document.createElement("td");
        if (st === "succeeded") {
          const b = document.createElement("button");
          b.type = "button";
          b.className = "btn btn-sm btn-outline-primary";
          b.textContent = "下载ZIP";
          b.addEventListener("click", function () {
            downloadZipById(j.id || "").catch(function (e) {
              showMsg(String(e.message || e), true);
            });
          });
          tdOp.appendChild(b);
        } else {
          const b = document.createElement("button");
          b.type = "button";
          b.className = "btn btn-sm btn-outline-secondary";
          b.textContent = "填入当前任务";
          b.addEventListener("click", function () {
            const inp = el("dg_local_job_id");
            if (inp) inp.value = j.id || "";
            const db = el("dg_btn_download");
            if (db) db.disabled = !j.hasLocalZip;
          });
          tdOp.appendChild(b);
        }
        if (j.hasPayloadSnapshot) {
          const rb = document.createElement("button");
          rb.type = "button";
          rb.className = "btn btn-sm btn-outline-success ms-1";
          rb.textContent = "相同参数";
          rb.addEventListener("click", function () { applyJobSnapshot(j.id || ""); });
          tdOp.appendChild(rb);
        }
        tr.appendChild(tdOp);
        tb.appendChild(tr);
      });
      var pg = (x.json && x.json.pagination) || {};
      _dgJobsPage = parseInt(pg.page || _dgJobsPage || 1, 10) || 1;
      _dgJobsTotalPages = parseInt(pg.total_pages || 1, 10) || 1;
      var info = el("dg_job_pager_info");
      if (info) info.textContent = "第 " + _dgJobsPage + "/" + _dgJobsTotalPages + " 页（共 " + (pg.total || 0) + " 条）";
      var prev = el("dg_job_prev");
      var next = el("dg_job_next");
      if (prev) prev.disabled = _dgJobsPage <= 1;
      if (next) next.disabled = _dgJobsPage >= _dgJobsTotalPages;
    });
  }

  var FILTER_SELECT_IDS = [
    "dg_base_case",
    "dg_doc_lang",
    "dg_strategy",
    "dg_author_role",
    "dg_project_id",
    "dg_page1_project_id",
  ];

  function wireSelectFilter(sid) {
    var fin = el(sid + "_filter");
    if (!fin || fin.getAttribute("data-dg-wired") === "1") return;
    fin.setAttribute("data-dg-wired", "1");
    function run() {
      applySelectSearchFilter(sid);
    }
    fin.addEventListener("input", run);
    fin.addEventListener("keyup", run);
    fin.addEventListener("change", run);
    fin.addEventListener("search", run);
    fin.addEventListener("paste", function () {
      window.setTimeout(run, 0);
    });
  }

  function wireTemplateFilterInput() {
    var tf = el("dg_template_filter");
    if (!tf || tf.getAttribute("data-dg-wired") === "1") return;
    tf.setAttribute("data-dg-wired", "1");
    function run() {
      applyTemplateCheckboxFilter();
    }
    tf.addEventListener("input", run);
    tf.addEventListener("keyup", run);
    tf.addEventListener("change", run);
    tf.addEventListener("search", run);
    tf.addEventListener("paste", function () {
      window.setTimeout(run, 0);
    });
  }

  function initDraftGenPage() {
    var ar0 = el("dg_author_role");
    if (ar0) {
      ar0.addEventListener("change", function () {
        _dgAuthorRoleUserTouched = true;
        setPrefillBadge("author", false);
      });
    }
    var sel = el("dg_provider");
    if (sel) sel.addEventListener("change", onProviderSelectChange);
    var b1 = el("dg_btn_save_llm");
    if (b1) b1.addEventListener("click", saveLlmSettings);
    var b1t = el("dg_btn_test_llm");
    if (b1t) b1t.addEventListener("click", testLlmSettings);
    var b2 = el("dg_btn_refresh_bootstrap");
    if (b2) b2.addEventListener("click", function () { loadDraftBootstrap(); });
    var ts = el("dg_template_scope");
    if (ts) ts.addEventListener("change", syncTemplateFilesUiDisabled);
    var inpl = el("dg_inplace");
    if (inpl) inpl.addEventListener("change", updateBaseRequirementUI);
    var tall = el("dg_btn_tpl_all");
    if (tall) tall.addEventListener("click", function () { setTemplateCheckboxesAll(true); });
    var tnone = el("dg_btn_tpl_none");
    if (tnone) tnone.addEventListener("click", function () { setTemplateCheckboxesAll(false); });
    var b3 = el("dg_btn_submit");
    if (b3) b3.addEventListener("click", submitJob);
    var b4 = el("dg_btn_download");
    if (b4) b4.addEventListener("click", downloadZip);
    var pPrev = el("dg_job_prev");
    if (pPrev) pPrev.addEventListener("click", function () {
      if (_dgJobsPage <= 1) return;
      _dgJobsPage -= 1;
      loadJobList();
    });
    var pNext = el("dg_job_next");
    if (pNext) pNext.addEventListener("click", function () {
      if (_dgJobsPage >= _dgJobsTotalPages) return;
      _dgJobsPage += 1;
      loadJobList();
    });
    var c1 = el("dg_base_case");
    if (c1) c1.addEventListener("change", loadDraftBootstrap);
    var pm = el("dg_project_mode");
    if (pm) {
      pm.addEventListener("change", function () {
        if (pm.value === "new") {
          _dgLinkedAcwProjectId = 0;
          updatePage1AcwLinkedLabel();
        }
        syncProjectUi();
      });
    }
    var p1sel = el("dg_page1_project_id");
    if (p1sel && p1sel.getAttribute("data-dg-p1-wired") !== "1") {
      p1sel.setAttribute("data-dg-p1-wired", "1");
      p1sel.addEventListener("change", function () {
        _dgLinkedAcwProjectId = 0;
        updatePage1AcwLinkedLabel();
        updatePage1CreateBtnState();
      });
    }
    var p1btn = el("dg_btn_open_acw_project_modal");
    if (p1btn) p1btn.addEventListener("click", openAcwProjectModal);
    var p1save = el("dg_btn_save_acw_project");
    if (p1save) p1save.addEventListener("click", saveAcwProjectFromModal);
    var pidSel = el("dg_project_id");
    if (pidSel && pidSel.getAttribute("data-dg-proj-defaults") !== "1") {
      pidSel.setAttribute("data-dg-proj-defaults", "1");
      pidSel.addEventListener("change", function () {
        var pid = parseInt(String(pidSel.value || "").trim(), 10) || 0;
        if (pid <= 0) return;
        api("/draft-gen/api/projects/" + pid + "/draft-defaults", { method: "GET" }).then(function (x) {
          if (!x.ok || !x.json || !x.json.data) return;
          var d = x.json.data;
          var dl = el("dg_doc_lang");
          if (dl && d.document_language_value !== undefined && d.document_language_value !== null) {
            var vals = Array.prototype.map.call(dl.options, function (o) { return o.value; });
            if (vals.indexOf(String(d.document_language_value)) >= 0) {
              dl.value = String(d.document_language_value);
              setPrefillBadge("doc_lang", true);
            }
          }
        });
      });
    }
    FILTER_SELECT_IDS.forEach(wireSelectFilter);
    wireTemplateFilterInput();
    wireDraftFilePickers();
    var cbt = el("dg_btn_clear_task_base");
    if (cbt && cbt.getAttribute("data-dg-wired") !== "1") {
      cbt.setAttribute("data-dg-wired", "1");
      cbt.addEventListener("click", function () {
        clearTaskBaseHintUi();
      });
    }
    var tbox = el("dg_template_files_box");
    if (tbox && tbox.getAttribute("data-dg-tpl-change") !== "1") {
      tbox.setAttribute("data-dg-tpl-change", "1");
      tbox.addEventListener("change", function (ev) {
        var t = ev.target;
        if (!t || t.getAttribute("data-template-name") == null) return;
        reorderTemplateCheckboxesSelectedFirst();
        updateTemplateSelectionSummary();
        scheduleApplyAuthorRoleSuggestion();
      });
    }
    updateTemplateSelectionSummary();
    return Promise.all([loadLlmSettings(), loadJobList(), loadDraftBootstrap()]);
  }

  function runDraftGenInit() {
    if (!el("dg_meta_preview") && !el("dg_job_rows")) return;
    return initDraftGenPage();
  }

  if (typeof registerPageInit === "function") {
    registerPageInit(runDraftGenInit);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", runDraftGenInit);
  } else {
    runDraftGenInit();
  }
})();
