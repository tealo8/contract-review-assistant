const { createApp, ref, computed, onMounted, onBeforeUnmount } = Vue;

createApp({
  setup() {
    const token = ref(localStorage.getItem('contract-token') || '');
    const user = ref(JSON.parse(localStorage.getItem('contract-user') || 'null'));
    const loginForm = ref({ username: 'legal', password: 'legal123' });
    const loginError = ref('');
    const projects = ref([]);
    const contracts = ref([]);
    const rules = ref([]);
    const knowledge = ref([]);
    const selected = ref(null);
    const activeView = ref('overview');
    const loading = ref(false);
    const working = ref('');
    const notice = ref(null);
    const search = ref('');
    const statusFilter = ref('全部状态');
    const dragActive = ref(false);
    const uploadFile = ref(null);
    const uploadProject = ref(1);
    const compareOld = ref('');
    const compareNew = ref('');
    const changes = ref([]);
    const compareRan = ref(false);
    const documentMode = ref('clauses');
    const reviewDrafts = ref({});
    const uploadModal = ref(false);
    const uploadProgress = ref(0);
    const uploadStage = ref('等待选择文件');
    const newRule = ref({ rule_name: '', rule_content: '', rule_type: 'keyword', description: '' });
    const editingRule = ref(null);
    const settingsTab = ref('rules');
    const adminLoading = ref(false);
    const adminRules = ref({ items: [], total: 0, page: 1, page_size: 8, pages: 1 });
    const adminKnowledge = ref({ items: [], total: 0, page: 1, page_size: 8, pages: 1 });
    const adminUsers = ref({ items: [], total: 0, page: 1, page_size: 8, pages: 1 });
    const knowledgeCategory = ref('law');
    const adminModal = ref(null);
    const confirmDialog = ref(null);
    const systemConfig = ref({ llm_api_url: '', chroma_host: '', chroma_port: '', chroma_collection: '', upload_storage_path: '', ai_risk_threshold: '' });
    const runtimeClientId = sessionStorage.getItem('runtime-client-id') || crypto.randomUUID();
    let heartbeatTimer = null;

    sessionStorage.setItem('runtime-client-id', runtimeClientId);

    const isLoggedIn = computed(() => Boolean(token.value && user.value));
    const roleName = computed(() => ({ admin: '管理员', legal_reviewer: '法务审核员', uploader: '上传人员' }[user.value?.role] || ''));
    const pendingReview = computed(() => contracts.value.filter(c => ['AI 审查完成', '待法务复核', '法务复核中'].includes(c.status)).length);
    const riskCounts = computed(() => {
      const counts = { '高': 0, '中': 0, '低': 0, '建议关注': 0 };
      contracts.value.forEach(contract => (contract.audit_results || []).forEach(risk => {
        if (counts[risk.risk_level] !== undefined) counts[risk.risk_level] += 1;
      }));
      return counts;
    });
    const filteredContracts = computed(() => contracts.value.filter(contract => {
      const matchesSearch = !search.value || `${contract.contract_name} ${contract.project_name} ${contract.username}`.toLowerCase().includes(search.value.toLowerCase());
      const matchesStatus = statusFilter.value === '全部状态' || contract.status === statusFilter.value;
      return matchesSearch && matchesStatus;
    }));
    const canReview = computed(() => ['admin', 'legal_reviewer'].includes(user.value?.role));
    const reviewReady = computed(() => Boolean(selected.value?.audit_results?.length) && selected.value.audit_results.every(risk => ['属实', '不属实'].includes(reviewDrafts.value[risk.id]?.legal_review_status)));

    const api = async (path, options = {}) => {
      const headers = { ...(options.headers || {}) };
      if (token.value) headers.Authorization = `Bearer ${token.value}`;
      const response = await fetch(`/api${path}`, { ...options, headers });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const error = new Error(data.detail || '请求失败，请稍后重试');
        error.status = response.status;
        throw error;
      }
      const type = response.headers.get('content-type') || '';
      return type.includes('application/json') ? response.json() : response.blob();
    };

    const flash = (message, type = 'success') => {
      const finalType = type === 'success' && /失败|错误|无权|无效|不能|不存在|请先|已被禁用/.test(message) ? 'error' : type;
      const next = { message, type: finalType, id: Date.now() };
      notice.value = next;
      window.setTimeout(() => { if (notice.value?.id === next.id) notice.value = null; }, 3600);
    };

    const go = view => {
      if (view === 'settings') return openSettings();
      activeView.value = view;
      if (view !== 'contract') selected.value = null;
      const paths = { overview: '/', contract: '/contracts', compare: '/version-compare', forbidden: '/403' };
      window.history.pushState({ view }, '', paths[view] || '/');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    const login = async () => {
      loginError.value = '';
      working.value = 'login';
      try {
        const data = await api('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(loginForm.value) });
        token.value = data.access_token;
        user.value = data.user;
        localStorage.setItem('contract-token', token.value);
        localStorage.setItem('contract-user', JSON.stringify(user.value));
        await loadAll();
        await handleRoute();
      } catch (error) {
        loginError.value = error.message;
      } finally {
        working.value = '';
      }
    };

    const logout = () => {
      token.value = '';
      user.value = null;
      selected.value = null;
      localStorage.removeItem('contract-token');
      localStorage.removeItem('contract-user');
      window.history.replaceState({}, '', '/');
    };

    const loadAll = async () => {
      if (!isLoggedIn.value) return;
      loading.value = true;
      try {
        user.value = await api('/auth/me');
        localStorage.setItem('contract-user', JSON.stringify(user.value));
        [projects.value, contracts.value, rules.value] = await Promise.all([api('/projects'), api('/contracts'), api('/rules')]);
        if (['admin', 'legal_reviewer'].includes(user.value.role)) knowledge.value = await api('/knowledge');
        if (projects.value.length && !projects.value.some(project => project.id === Number(uploadProject.value))) uploadProject.value = projects.value[0].id;
      } catch (error) {
        if (error.message.includes('登录')) logout();
        else flash(error.message);
      } finally {
        loading.value = false;
      }
    };

    const openUploadModal = () => {
      uploadModal.value = true;
      uploadProgress.value = 0;
      uploadStage.value = uploadFile.value ? '文件已就绪' : '等待选择文件';
    };

    const pickFile = event => {
      uploadFile.value = event.target.files?.[0] || null;
      uploadStage.value = uploadFile.value ? '文件已就绪' : '等待选择文件';
      if (uploadFile.value && event.target.id !== 'file-input') {
        uploadModal.value = true;
      }
    };
    const dropFile = event => {
      dragActive.value = false;
      uploadFile.value = event.dataTransfer.files?.[0] || null;
      uploadStage.value = uploadFile.value ? '文件已就绪' : '等待选择文件';
    };

    const upload = async () => {
      if (!uploadFile.value) return flash('请先选择合同文件', 'warning');
      working.value = 'upload';
      uploadProgress.value = 0;
      uploadStage.value = '正在上传文件';
      const body = new FormData();
      body.append('file', uploadFile.value);
      try {
        const data = await new Promise((resolve, reject) => {
          const request = new XMLHttpRequest();
          request.open('POST', `/api/contracts/upload?project_id=${uploadProject.value}`);
          request.setRequestHeader('Authorization', `Bearer ${token.value}`);
          request.upload.onprogress = event => {
            if (!event.lengthComputable) return;
            uploadProgress.value = Math.round((event.loaded / event.total) * 100);
            if (uploadProgress.value >= 100) uploadStage.value = '文件上传完成，正在解析合同条款';
          };
          request.onload = () => {
            const payload = JSON.parse(request.responseText || '{}');
            if (request.status >= 200 && request.status < 300) resolve(payload);
            else reject(new Error(payload.detail || payload.message || '合同上传失败'));
          };
          request.onerror = () => reject(new Error('网络连接失败，无法上传合同'));
          request.send(body);
        });
        uploadStage.value = '解析完成';
        uploadFile.value = null;
        document.querySelectorAll('input[type="file"]').forEach(input => { input.value = ''; });
        await loadAll();
        uploadModal.value = false;
        flash(data.message || '合同上传并解析成功');
      } catch (error) {
        uploadStage.value = '上传或解析失败';
        flash(error.message, 'error');
      } finally {
        working.value = '';
      }
    };

    const initReviewDrafts = contract => {
      reviewDrafts.value = Object.fromEntries((contract.audit_results || []).map(risk => [risk.id, {
        legal_review_status: ['属实', '不属实'].includes(risk.legal_review_status) ? risk.legal_review_status : '',
        legal_comment: risk.legal_comment || ''
      }]));
    };

    const openContract = async (id, updateHistory = true) => {
      working.value = `contract-${id}`;
      try {
        selected.value = await api(`/contracts/${id}`);
        initReviewDrafts(selected.value);
        documentMode.value = 'clauses';
        activeView.value = 'contract';
        if (updateHistory) window.history.pushState({ view: 'contract', id }, '', `/contracts/${id}`);
        window.scrollTo({ top: 0, behavior: 'smooth' });
      } catch (error) {
        flash(error.message);
      } finally {
        working.value = '';
      }
    };

    const backToContracts = () => {
      selected.value = null;
      activeView.value = 'contract';
      window.history.pushState({ view: 'contract' }, '', '/contracts');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    const audit = async id => {
      working.value = 'audit';
      try {
        const data = await api(`/contracts/${id}/audit`, { method: 'POST' });
        selected.value = data.contract;
        initReviewDrafts(selected.value);
        await loadAll();
        flash('AI 审查完成，风险依据已锁定');
      } catch (error) {
        flash(error.message);
      } finally {
        working.value = '';
      }
    };

    const downloadReport = async (id, format) => {
      working.value = `report-${format}`;
      try {
        const blob = await api(`/contracts/${id}/report?format=${format}`);
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `contract-${id}-report.${format}`;
        anchor.click();
        URL.revokeObjectURL(url);
      } catch (error) {
        flash(error.message);
      } finally {
        working.value = '';
      }
    };

    const completeReview = async () => {
      if (!reviewReady.value) return flash('请先为全部风险选择属实或不属实', 'warning');
      working.value = 'complete-review';
      try {
        const decisions = selected.value.audit_results.map(risk => ({ risk_id: risk.id, ...reviewDrafts.value[risk.id] }));
        const data = await api(`/contracts/${selected.value.id}/review/complete`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decisions }) });
        selected.value = data.contract;
        initReviewDrafts(selected.value);
        await loadAll();
        flash('法务复核已完成');
      } catch (error) {
        flash(error.message, 'error');
      } finally {
        working.value = '';
      }
    };

    const compare = async () => {
      if (!compareOld.value || !compareNew.value) return flash('请选择两个合同版本', 'warning');
      if (compareOld.value === compareNew.value) return flash('请选择不同的合同版本', 'warning');
      working.value = 'compare';
      try {
        const data = await api(`/contracts/compare?old_id=${compareOld.value}&new_id=${compareNew.value}`, { method: 'POST' });
        changes.value = data.changes;
        compareRan.value = true;
        if (!changes.value.length) flash('两个版本未发现条款变化', 'warning');
      } catch (error) {
        flash(error.message);
      } finally {
        working.value = '';
      }
    };

    const addRule = async () => {
      if (!newRule.value.rule_name.trim() || !newRule.value.rule_content.trim()) return flash('请填写规则名称和内容');
      working.value = 'rule';
      try {
        await api('/rules', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newRule.value) });
        newRule.value = { rule_name: '', rule_content: '', rule_type: 'keyword', description: '' };
        await loadAll();
        flash('规则已保存');
      } catch (error) {
        flash(error.message);
      } finally {
        working.value = '';
      }
    };

    const toggleRule = async rule => {
      try {
        await api(`/rules/${rule.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enable: !rule.enable }) });
        await loadAll();
      } catch (error) {
        flash(error.message);
      }
    };

    const openRuleEditor = rule => { editingRule.value = { ...rule, enable: Boolean(rule.enable) }; };
    const saveRule = async () => {
      if (!editingRule.value) return;
      working.value = 'edit-rule';
      try {
        await api(`/rules/${editingRule.value.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rule_name: editingRule.value.rule_name, rule_content: editingRule.value.rule_content, rule_type: editingRule.value.rule_type, description: editingRule.value.description, enable: editingRule.value.enable })
        });
        editingRule.value = null;
        await loadAll();
        flash('规则已更新');
      } catch (error) {
        flash(error.message);
      } finally {
        working.value = '';
      }
    };

    const denySettings = async () => {
      try { await api('/admin/config'); } catch (_) { /* The server records the required 403 authorization decision. */ }
      activeView.value = 'forbidden';
      selected.value = null;
      window.history.replaceState({ view: 'forbidden' }, '', '/403');
      flash('您没有管理员权限', 'warning');
    };

    const openSettings = async (tab = settingsTab.value) => {
      if (user.value?.role !== 'admin') return denySettings();
      activeView.value = 'settings';
      selected.value = null;
      settingsTab.value = tab;
      window.history.pushState({ view: 'settings' }, '', '/system-settings');
      window.scrollTo({ top: 0, behavior: 'smooth' });
      await loadAdminTab(tab);
    };

    const loadAdminTab = async (tab = settingsTab.value, page = 1) => {
      if (user.value?.role !== 'admin') return denySettings();
      settingsTab.value = tab;
      adminLoading.value = true;
      try {
        if (tab === 'rules') adminRules.value = await api(`/admin/rules?page=${page}&page_size=${adminRules.value.page_size}`);
        if (tab === 'knowledge') adminKnowledge.value = await api(`/admin/knowledge?page=${page}&page_size=${adminKnowledge.value.page_size}&category=${knowledgeCategory.value}`);
        if (tab === 'users') adminUsers.value = await api(`/admin/users?page=${page}&page_size=${adminUsers.value.page_size}`);
        if (tab === 'config') {
          const data = await api('/admin/config');
          systemConfig.value = { ...systemConfig.value, ...data.config };
        }
      } catch (error) {
        if (error.status === 403) return denySettings();
        flash(error.message);
      } finally {
        adminLoading.value = false;
      }
    };

    const selectSettingsTab = tab => loadAdminTab(tab, 1);
    const changeKnowledgeCategory = category => {
      knowledgeCategory.value = category;
      loadAdminTab('knowledge', 1);
    };

    const openAdminModal = (type, item = null, mode = item ? 'edit' : 'create') => {
      const defaults = {
        rule: { rule_name: '', rule_type: 'keyword', rule_content: '', risk_level: '中', description: '', enable: true },
        knowledge: { category: knowledgeCategory.value, title: '', content: '', reference_no: '', enable: true },
        user: { username: '', display_name: '', password: '', role: 'uploader' },
        password: { password: '' }
      };
      adminModal.value = { type, mode, data: { ...(defaults[type] || {}), ...(item || {}) } };
    };

    const submitAdminModal = async () => {
      if (!adminModal.value) return;
      const { type, mode, data } = adminModal.value;
      working.value = 'admin-modal';
      try {
        if (type === 'rule') await api(mode === 'create' ? '/admin/rules' : `/admin/rules/${data.id}`, { method: mode === 'create' ? 'POST' : 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        if (type === 'knowledge') await api(mode === 'create' ? '/admin/knowledge' : `/admin/knowledge/${data.id}`, { method: mode === 'create' ? 'POST' : 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        if (type === 'user') await api('/admin/users', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        if (type === 'password') await api(`/admin/users/${data.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: data.password }) });
        adminModal.value = null;
        await loadAdminTab(type === 'rule' ? 'rules' : type === 'knowledge' ? 'knowledge' : 'users');
        flash(type === 'password' ? '密码重置成功' : mode === 'create' ? '新增成功' : '修改成功');
      } catch (error) {
        flash(error.message);
      } finally {
        working.value = '';
      }
    };

    const updateAdminRule = async (rule, values) => {
      try {
        await api(`/admin/rules/${rule.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) });
        await loadAdminTab('rules', adminRules.value.page);
        flash(values.enable === undefined ? '规则已更新' : values.enable ? '规则已启用' : '规则已禁用');
      } catch (error) { flash(error.message); }
    };

    const updateAdminKnowledge = async (item, values) => {
      try {
        await api(`/admin/knowledge/${item.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) });
        await loadAdminTab('knowledge', adminKnowledge.value.page);
        flash(values.enable ? '知识条目已启用' : '知识条目已禁用');
      } catch (error) { flash(error.message); }
    };

    const updateAdminUser = async (item, values) => {
      try {
        await api(`/admin/users/${item.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) });
        await loadAdminTab('users', adminUsers.value.page);
        flash('账号信息已更新');
      } catch (error) {
        flash(error.message);
        await loadAdminTab('users', adminUsers.value.page);
      }
    };

    const askDelete = (type, item) => {
      const names = { rule: item.rule_name, knowledge: item.title, user: item.display_name || item.username };
      confirmDialog.value = { type, item, name: names[type] };
    };

    const confirmDelete = async () => {
      if (!confirmDialog.value) return;
      const { type, item } = confirmDialog.value;
      const endpoints = { rule: `/admin/rules/${item.id}`, knowledge: `/admin/knowledge/${item.id}`, user: `/admin/users/${item.id}` };
      working.value = 'delete';
      try {
        await api(endpoints[type], { method: 'DELETE' });
        confirmDialog.value = null;
        await loadAdminTab(type === 'rule' ? 'rules' : type === 'knowledge' ? 'knowledge' : 'users');
        flash('删除成功');
      } catch (error) {
        flash(error.message);
      } finally {
        working.value = '';
      }
    };

    const saveSystemConfig = async () => {
      working.value = 'config';
      try {
        const data = await api('/admin/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(systemConfig.value) });
        systemConfig.value = { ...systemConfig.value, ...data.config };
        confirmDialog.value = null;
        flash(data.vector_sync?.fallback ? '系统参数已保存，向量服务不可用，当前使用本地检索降级' : '系统参数保存成功', data.vector_sync?.fallback ? 'warning' : 'success');
      } catch (error) {
        flash(error.message);
      } finally {
        working.value = '';
      }
    };

    const askConfigSave = () => {
      confirmDialog.value = { type: 'config', name: '系统运行参数' };
    };

    const confirmAction = () => confirmDialog.value?.type === 'config' ? saveSystemConfig() : confirmDelete();

    const handleRoute = async () => {
      const path = window.location.pathname;
      const contractMatch = path.match(/^\/contracts\/(\d+)$/);
      if (path === '/system-settings') {
        if (user.value?.role === 'admin') {
          activeView.value = 'settings';
          await loadAdminTab(settingsTab.value);
        } else {
          await denySettings();
        }
      } else if (contractMatch) {
        await openContract(Number(contractMatch[1]), false);
      } else if (path === '/contracts') {
        activeView.value = 'contract';
        selected.value = null;
      } else if (path === '/version-compare') {
        activeView.value = 'compare';
        selected.value = null;
      } else if (path === '/403') {
        activeView.value = 'forbidden';
        selected.value = null;
      } else {
        activeView.value = 'overview';
        selected.value = null;
      }
    };

    const heartbeat = () => fetch('/api/runtime/heartbeat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ client_id: runtimeClientId }), keepalive: true }).catch(() => {});
    const notifyPageClose = () => {
      const payload = new Blob([JSON.stringify({ client_id: runtimeClientId })], { type: 'application/json' });
      navigator.sendBeacon('/api/runtime/page-closed', payload);
    };

    onMounted(() => {
      loadAll().then(handleRoute);
      heartbeat();
      heartbeatTimer = window.setInterval(heartbeat, 2000);
      window.addEventListener('pagehide', notifyPageClose);
      window.addEventListener('popstate', handleRoute);
    });
    onBeforeUnmount(() => {
      window.clearInterval(heartbeatTimer);
      window.removeEventListener('pagehide', notifyPageClose);
      window.removeEventListener('popstate', handleRoute);
    });

    return { user, loginForm, loginError, projects, contracts, rules, knowledge, selected, activeView, loading, working, notice, search, statusFilter, dragActive, uploadFile, uploadProject, uploadModal, uploadProgress, uploadStage, compareOld, compareNew, changes, compareRan, documentMode, reviewDrafts, canReview, reviewReady, newRule, editingRule, settingsTab, adminLoading, adminRules, adminKnowledge, adminUsers, knowledgeCategory, adminModal, confirmDialog, systemConfig, isLoggedIn, roleName, pendingReview, riskCounts, filteredContracts, go, login, logout, loadAll, openUploadModal, pickFile, dropFile, upload, openContract, backToContracts, audit, downloadReport, completeReview, compare, addRule, toggleRule, openRuleEditor, saveRule, openSettings, selectSettingsTab, changeKnowledgeCategory, openAdminModal, submitAdminModal, updateAdminRule, updateAdminKnowledge, updateAdminUser, askDelete, confirmDelete, askConfigSave, confirmAction, saveSystemConfig, loadAdminTab };
  },
  template: `
    <div v-if="!isLoggedIn" class="login-page">
      <header class="public-nav"><a class="wordmark" href="#" aria-label="合同智能审查助手首页"><img class="wordmark-logo" src="/assets/contract-review-logo.svg" alt=""><strong>合同智能审查助手</strong></a><span class="nav-note">AI 辅助审查</span></header>
      <main class="login-main">
        <section class="login-intro"><span class="section-label">Contract Intelligence</span><h1>每一条风险，<br>都有据可循。</h1><p>合同解析、规则校验、依据检索与人工复核，在同一处完成。</p></section>
        <section class="login-card" aria-labelledby="login-title"><h2 id="login-title">登录工作台</h2><p>使用组织账号继续</p><form @submit.prevent="login"><label>账号<input v-model="loginForm.username" autocomplete="username" placeholder="请输入账号"></label><label>密码<input type="password" v-model="loginForm.password" autocomplete="current-password" placeholder="请输入密码"></label><button class="button button-primary button-wide" type="submit" :disabled="working==='login'">{{ working==='login' ? '正在登录…' : '继续' }}</button></form><p v-if="loginError" class="form-error">{{ loginError }}</p><p class="demo-accounts">演示账号：legal / legal123</p></section>
      </main>
      <footer class="simple-footer">本系统输出仅供辅助参考，不替代专业法务审核。</footer>
    </div>

    <div v-else class="product-shell">
      <header class="product-nav"><div class="nav-inner"><button class="wordmark wordmark-button" @click="go('overview')" aria-label="返回总览"><img class="wordmark-logo" src="/assets/contract-review-logo.svg" alt=""><strong>合同智能审查助手</strong></button><nav aria-label="主导航"><button :class="{ active: activeView==='overview' }" @click="go('overview')">总览</button><button :class="{ active: activeView==='contract' }" @click="go('contract')">合同记录</button><button :class="{ active: activeView==='compare' }" @click="go('compare')">版本比对</button><button v-if="user.role==='admin'" :class="{ active: activeView==='settings' }" @click="go('settings')">系统设置</button></nav><div class="account-menu"><span class="account-avatar">{{ user.username.slice(0,1).toUpperCase() }}</span><span class="account-copy"><strong>{{ user.username }}</strong><small>{{ roleName }}</small></span><button class="icon-button" title="退出登录" aria-label="退出登录" @click="logout">↗</button></div></div></header>
      <div v-if="loading" class="loading-line" aria-label="正在加载"></div>
      <transition name="toast"><div v-if="notice" class="toast-message" :class="'toast-'+notice.type" role="status">{{ notice.message }}</div></transition>

      <main class="page-shell">
        <div v-if="loading && !contracts.length" class="page-skeleton" aria-label="页面加载中"><i></i><i></i><i></i></div>
        <section v-if="activeView==='overview'" class="view-fade">
          <section class="product-hero"><span class="section-label">AI-assisted legal review</span><h1>合同审查，<br>清晰到每一条依据。</h1><p>从文档解析到法务复核，风险结论始终与法条或企业规则保持绑定。</p><div class="hero-actions"><button class="button button-primary" @click="openUploadModal">上传合同</button><button class="button button-text" @click="go('contract')">查看合同记录 <span>›</span></button></div></section>
          <section class="metric-strip" aria-label="审查概览"><div><strong>{{ contracts.length }}</strong><span>合同总数</span></div><div><strong>{{ riskCounts['高'] }}</strong><span>高风险</span></div><div><strong>{{ pendingReview }}</strong><span>待复核</span></div><div><strong>{{ rules.filter(rule=>rule.enable).length }}</strong><span>启用规则</span></div></section>
          <section class="shortcut-grid" aria-label="快捷功能"><button class="shortcut-card" @click="openUploadModal"><span class="shortcut-index">01</span><strong>新建审查</strong><p>上传合同并开始条款解析</p><span class="shortcut-link">开始 <b>›</b></span></button><button class="shortcut-card" @click="go('contract')"><span class="shortcut-index">02</span><strong>合同记录</strong><p>查看项目、版本与审查状态</p><span class="shortcut-link">查看 <b>›</b></span></button><button class="shortcut-card" @click="go('compare')"><span class="shortcut-index">03</span><strong>版本比对</strong><p>按条款定位版本变化</p><span class="shortcut-link">比对 <b>›</b></span></button><button v-if="user.role==='admin'" class="shortcut-card" @click="openSettings('rules')"><span class="shortcut-index">04</span><strong>规则中心</strong><p>维护企业审查约束</p><span class="shortcut-link">管理 <b>›</b></span></button><button v-else class="shortcut-card" @click="go('contract')"><span class="shortcut-index">04</span><strong>人工复核</strong><p>确认 AI 风险与法务意见</p><span class="shortcut-link">处理 <b>›</b></span></button></section>
          <section class="workspace-section"><div class="section-heading"><div><span class="section-label">New review</span><h2>上传合同</h2></div><p>PDF、DOCX 或可复制文本文件</p></div><div class="upload-workspace"><div class="upload-drop" :class="{ active: dragActive, selected: uploadFile }" @click="$refs.file.click()" @dragover.prevent="dragActive=true" @dragleave.prevent="dragActive=false" @drop.prevent="dropFile"><input id="file-input" ref="file" type="file" accept=".pdf,.docx,.txt,.md" hidden @change="pickFile"><span class="upload-symbol">↑</span><strong>{{ uploadFile ? uploadFile.name : '选择合同文件' }}</strong><small>{{ uploadFile ? '文件已就绪' : '也可以拖放到这里，最大 20MB' }}</small></div><div class="upload-controls"><label>归属项目<select v-model="uploadProject"><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.project_name }}</option></select></label><button class="button button-primary" :disabled="!uploadFile || working==='upload'" @click="upload">{{ working==='upload' ? '正在上传…' : '开始审查' }}</button></div></div></section>
          <section class="recent-section"><div class="section-heading"><div><span class="section-label">Recent activity</span><h2>最近合同</h2></div><button class="button button-text" @click="go('contract')">查看全部 <span>›</span></button></div><div class="record-list"><button v-for="contract in contracts.slice(0,5)" :key="contract.id" class="record-row" @click="openContract(contract.id)"><span class="document-symbol">D</span><span class="record-main"><strong>{{ contract.contract_name }}</strong><small>{{ contract.project_name }} · {{ contract.version }}</small></span><span class="status-pill" :class="contract.status.includes('完成') ? 'complete' : contract.status==='待审查' ? 'waiting' : 'reviewing'">{{ contract.status }}</span><time>{{ new Date(contract.upload_time).toLocaleDateString('zh-CN') }}</time><span class="row-chevron">›</span></button><div v-if="!contracts.length" class="empty-state">还没有合同记录</div></div></section>
        </section>

        <section v-else-if="activeView==='contract'" class="view-fade">
          <template v-if="!selected"><header class="page-heading"><span class="section-label">Contracts</span><h1>合同记录</h1><p>查看全部版本、审查状态与历史报告。</p></header><div class="filter-bar"><label class="search-field"><span>⌕</span><input v-model="search" placeholder="搜索合同或项目"></label><select v-model="statusFilter"><option>全部状态</option><option>上传中</option><option>解析中</option><option>待审查</option><option>待法务复核</option><option>法务复核中</option><option>复核完成</option><option>解析失败</option></select></div><div class="record-list record-list-large"><button v-for="contract in filteredContracts" :key="contract.id" class="record-row" @click="openContract(contract.id)"><span class="document-symbol">D</span><span class="record-main"><strong>{{ contract.contract_name }}</strong><small>{{ contract.project_name }} · 上传人 {{ contract.username }}</small></span><span class="version-pill">{{ contract.version }}</span><span class="status-pill" :class="contract.status.includes('完成') ? 'complete' : contract.status==='待审查' ? 'waiting' : 'reviewing'">{{ contract.status }}</span><time>{{ new Date(contract.upload_time).toLocaleDateString('zh-CN') }}</time><span class="row-chevron">›</span></button><div v-if="!filteredContracts.length" class="empty-state">没有符合条件的合同</div></div></template>
          <template v-else>
            <button class="back-link" @click="backToContracts">‹ 返回合同记录</button>
            <header class="contract-heading"><div><span class="section-label">{{ selected.project_name }} · {{ selected.version }}</span><h1>{{ selected.contract_name }}</h1><p>上传人 {{ selected.username }} · {{ new Date(selected.upload_time).toLocaleString('zh-CN') }}</p></div><div class="heading-actions"><button class="button button-secondary" @click="downloadReport(selected.id,'pdf')">导出 PDF 报告</button><button class="button button-primary" :disabled="working==='audit'" @click="audit(selected.id)">{{ working==='audit' ? '正在审查…' : '运行 AI 审查' }}</button></div></header>
            <div class="contract-layout">
              <section class="content-panel document-panel">
                <div class="panel-title"><div><span class="section-label">Document</span><h2>合同原始文档</h2></div><div class="document-tabs"><button :class="{active:documentMode==='clauses'}" @click="documentMode='clauses'">结构化条款</button><button :class="{active:documentMode==='original'}" @click="documentMode='original'">原始全文</button></div></div>
                <template v-if="documentMode==='clauses'"><article v-for="clause in selected.clauses" :key="clause.id" class="clause-row"><strong>{{ clause.clause_type }}</strong><p>{{ clause.clause_content }}</p></article><div v-if="!selected.clauses.length" class="empty-state">尚未识别到合同条款</div></template>
                <pre v-else-if="selected.original_text" class="original-document">{{ selected.original_text }}</pre><div v-else class="empty-state">暂无可预览的原始文本</div>
                <p v-if="selected.parse_error" class="form-error">{{ selected.parse_error }}</p>
              </section>
              <section class="content-panel risk-panel">
                <div class="panel-title"><div><span class="section-label">AI Review</span><h2>审查风险清单</h2></div><span>{{ selected.audit_results.length }} 项</span></div>
                <article v-for="risk in selected.audit_results" :key="risk.id" class="risk-row"><div class="risk-meta"><span class="risk-pill" :class="risk.risk_level==='高' ? 'high' : risk.risk_level==='中' ? 'medium' : 'low'">{{ risk.risk_level }}风险</span><span>{{ risk.clause_type }}</span><span class="review-state">{{ risk.legal_review_status }}</span></div><h3>{{ risk.risk_desc }}</h3><dl><div><dt>依据</dt><dd><span class="source-badge">{{ risk.source_type==='rule' || risk.source_reference.includes('企业规则') ? '审查规则' : '知识库依据' }}</span>{{ risk.source_reference }}</dd></div><div><dt>建议</dt><dd>{{ risk.suggestion }}</dd></div></dl><div v-if="canReview && selected.status!=='复核完成'" class="review-draft"><div class="truth-control" role="group" aria-label="风险判定"><button :class="{active:reviewDrafts[risk.id]?.legal_review_status==='属实'}" @click="reviewDrafts[risk.id].legal_review_status='属实'">属实</button><button :class="{active:reviewDrafts[risk.id]?.legal_review_status==='不属实'}" @click="reviewDrafts[risk.id].legal_review_status='不属实'">不属实</button></div><input v-model="reviewDrafts[risk.id].legal_comment" placeholder="填写复核意见（选填）"></div></article>
                <div v-if="!selected.audit_results.length" class="empty-state">运行 AI 审查后，在这里查看风险依据与修改建议</div>
                <div v-if="canReview && selected.audit_results.length && selected.status!=='复核完成'" class="review-submit"><span>{{ reviewReady ? '全部风险已判定，可以提交复核' : '请逐条完成属实性判定' }}</span><button class="button button-primary" :disabled="!reviewReady || working==='complete-review'" @click="completeReview">{{ working==='complete-review'?'正在提交…':'提交复核完成' }}</button></div>
              </section>
            </div>
            <section class="status-history"><div class="panel-title"><div><span class="section-label">Workflow</span><h2>状态流转记录</h2></div></div><ol><li v-for="entry in selected.status_history" :key="entry.id"><span></span><div><strong>{{ entry.status }}</strong><small>{{ entry.operator || '系统' }} · {{ new Date(entry.operated_at).toLocaleString('zh-CN') }}</small></div></li></ol></section>
          </template>
        </section>

        <section v-else-if="activeView==='compare'" class="view-fade"><header class="page-heading"><span class="section-label">Version comparison</span><h1>版本比对</h1><p>按条款并排查看新增、删除与修改内容。</p></header><section class="compare-config"><div class="compare-selects"><label>旧版本<select v-model="compareOld" @change="compareRan=false;changes=[]"><option value="">请选择合同</option><option v-for="contract in contracts" :key="contract.id" :value="contract.id">{{ contract.contract_name }} · {{ contract.version }}</option></select></label><span class="compare-arrow">→</span><label>新版本<select v-model="compareNew" @change="compareRan=false;changes=[]"><option value="">请选择合同</option><option v-for="contract in contracts" :key="contract.id" :value="contract.id">{{ contract.contract_name }} · {{ contract.version }}</option></select></label></div><button class="button button-primary" :disabled="working==='compare'" @click="compare">{{ working==='compare' ? '正在比对…' : '生成差异' }}</button></section><section v-if="changes.length" class="diff-results"><div class="panel-title"><div><span class="section-label">Changes</span><h2>条款变化</h2></div><span>{{ changes.length }} 项</span></div><article v-for="change in changes" :key="change.clause_type" class="diff-item" :class="change.change_type"><header><span class="change-dot"></span><strong>{{ change.clause_type }}</strong><em>{{ {added:'新增',deleted:'删除',modified:'修改'}[change.change_type] }}</em></header><div class="diff-columns"><div><small>旧版本</small><p>{{ change.before || '无对应条款' }}</p></div><div><small>新版本</small><p>{{ change.after || '无对应条款' }}</p></div></div></article></section><div v-else class="blank-state"><span>⇄</span><h2>{{ compareRan ? '两个版本没有差异' : '选择两个合同版本' }}</h2><p>{{ compareRan ? '未发现新增、删除或修改的条款。' : '差异会按条款并列展示。' }}</p></div></section>

        <section v-else-if="activeView==='forbidden'" class="view-fade forbidden-page"><span class="forbidden-code">403</span><h1>您没有管理员权限</h1><p>系统设置仅对管理员开放，当前账号不能访问此页面。</p><button class="button button-primary" @click="go('overview')">返回总览</button></section>

        <section v-else-if="activeView==='settings'" class="view-fade settings-page">
          <header class="page-heading"><span class="section-label">Administration</span><h1>系统设置</h1><p>集中维护审查规则、知识依据、组织账号与运行参数。</p></header>
          <nav class="settings-tabs" aria-label="系统设置分类"><button :class="{active:settingsTab==='rules'}" @click="selectSettingsTab('rules')">审查规则管理</button><button :class="{active:settingsTab==='knowledge'}" @click="selectSettingsTab('knowledge')">知识库管理</button><button :class="{active:settingsTab==='users'}" @click="selectSettingsTab('users')">用户账号管理</button><button :class="{active:settingsTab==='config'}" @click="selectSettingsTab('config')">系统参数配置</button></nav>

          <section v-if="settingsTab==='rules'" class="settings-card"><div class="settings-toolbar"><div><h2>审查规则管理</h2><p>规则保存后立即由审查引擎读取，无需重启服务。</p></div><button class="button button-primary" @click="openAdminModal('rule')">新增规则</button></div><div v-if="adminLoading" class="table-skeleton"><i v-for="n in 6" :key="n"></i></div><div v-else class="admin-table-wrap"><table class="admin-table"><thead><tr><th>ID</th><th>规则名称</th><th>规则类型</th><th>规则条件描述</th><th>是否启用</th><th>操作</th></tr></thead><tbody><tr v-for="rule in adminRules.items" :key="rule.id"><td>#{{ rule.id }}</td><td><strong>{{ rule.rule_name }}</strong><small>风险等级：{{ rule.risk_level }}</small></td><td><span class="type-pill">{{ {num:'数值',regex:'正则',keyword:'关键词'}[rule.rule_type] }}</span></td><td class="condition-cell"><strong>{{ rule.rule_content }}</strong><small>{{ rule.description || '暂无描述' }}</small></td><td><button class="switch" :class="{on:rule.enable}" @click="updateAdminRule(rule,{enable:!rule.enable})"><span></span></button></td><td><div class="table-actions"><button @click="openAdminModal('rule',rule)">编辑</button><button class="danger-link" @click="askDelete('rule',rule)">删除</button></div></td></tr></tbody></table><div v-if="!adminRules.items.length" class="empty-state">暂无业务审查规则</div></div><div class="pagination"><span>共 {{ adminRules.total }} 条</span><div><button :disabled="adminRules.page<=1" @click="loadAdminTab('rules',adminRules.page-1)">上一页</button><b>{{ adminRules.page }} / {{ adminRules.pages }}</b><button :disabled="adminRules.page>=adminRules.pages" @click="loadAdminTab('rules',adminRules.page+1)">下一页</button></div></div></section>

          <section v-else-if="settingsTab==='knowledge'" class="settings-card"><div class="settings-toolbar"><div><h2>知识库管理</h2><p>仅启用的法条与企业规范参与 RAG 检索。</p></div><button class="button button-primary" @click="openAdminModal('knowledge')">新增条目</button></div><div class="segmented-control"><button :class="{active:knowledgeCategory==='law'}" @click="changeKnowledgeCategory('law')">民法典法条库</button><button :class="{active:knowledgeCategory==='enterprise_spec'}" @click="changeKnowledgeCategory('enterprise_spec')">企业合同规范库</button></div><div v-if="adminLoading" class="table-skeleton"><i v-for="n in 6" :key="n"></i></div><div v-else class="admin-table-wrap"><table class="admin-table knowledge-table"><thead><tr><th>ID</th><th>知识库分类</th><th>标题</th><th>内容</th><th>参考编号</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="item in adminKnowledge.items" :key="item.id"><td>#{{ item.id }}</td><td><span class="type-pill">{{ item.category==='law'?'民法典法条':'企业规范' }}</span></td><td><strong>{{ item.title }}</strong></td><td class="knowledge-content">{{ item.content }}</td><td><code>{{ item.reference_no }}</code></td><td><button class="switch" :class="{on:item.enable}" @click="updateAdminKnowledge(item,{enable:!item.enable})"><span></span></button></td><td><div class="table-actions"><button @click="openAdminModal('knowledge',item)">编辑</button><button class="danger-link" @click="askDelete('knowledge',item)">删除</button></div></td></tr></tbody></table><div v-if="!adminKnowledge.items.length" class="empty-state">当前分类暂无知识条目</div></div><div class="pagination"><span>共 {{ adminKnowledge.total }} 条</span><div><button :disabled="adminKnowledge.page<=1" @click="loadAdminTab('knowledge',adminKnowledge.page-1)">上一页</button><b>{{ adminKnowledge.page }} / {{ adminKnowledge.pages }}</b><button :disabled="adminKnowledge.page>=adminKnowledge.pages" @click="loadAdminTab('knowledge',adminKnowledge.page+1)">下一页</button></div></div></section>

          <section v-else-if="settingsTab==='users'" class="settings-card"><div class="settings-toolbar"><div><h2>用户账号管理</h2><p>管理组织角色与账号状态，密码始终使用 bcrypt 哈希存储。</p></div><button class="button button-primary" @click="openAdminModal('user')">新增账号</button></div><div v-if="adminLoading" class="table-skeleton"><i v-for="n in 6" :key="n"></i></div><div v-else class="admin-table-wrap"><table class="admin-table"><thead><tr><th>用户名</th><th>显示名称</th><th>角色</th><th>账号状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody><tr v-for="account in adminUsers.items" :key="account.id"><td><strong>{{ account.username }}</strong></td><td>{{ account.display_name }}</td><td><select class="table-select" :value="account.role" @change="updateAdminUser(account,{role:$event.target.value})"><option value="uploader">uploader</option><option value="legal_reviewer">legal_reviewer</option><option value="admin">admin</option></select></td><td><div class="status-switch"><button class="switch" :class="{on:account.enable}" @click="updateAdminUser(account,{enable:!account.enable})"><span></span></button><small>{{ account.enable?'启用':'禁用' }}</small></div></td><td>{{ new Date(account.created_at).toLocaleDateString('zh-CN') }}</td><td><div class="table-actions"><button @click="openAdminModal('password',{id:account.id,username:account.username},'reset')">重置密码</button><button class="danger-link" @click="askDelete('user',account)">删除</button></div></td></tr></tbody></table><div v-if="!adminUsers.items.length" class="empty-state">暂无用户账号</div></div><div class="pagination"><span>共 {{ adminUsers.total }} 个账号</span><div><button :disabled="adminUsers.page<=1" @click="loadAdminTab('users',adminUsers.page-1)">上一页</button><b>{{ adminUsers.page }} / {{ adminUsers.pages }}</b><button :disabled="adminUsers.page>=adminUsers.pages" @click="loadAdminTab('users',adminUsers.page+1)">下一页</button></div></div></section>

          <section v-else class="settings-card config-card"><div class="settings-toolbar"><div><h2>系统参数配置</h2><p>修改将保存至系统配置表，请在确认服务参数有效后提交。</p></div></div><form class="config-form" @submit.prevent="askConfigSave"><div class="config-section"><span class="config-index">01</span><div><h3>LLM 模型服务</h3><p>兼容 OpenAI API 协议的模型服务入口。</p></div><label>API 地址<input v-model="systemConfig.llm_api_url" required placeholder="http://localhost:8000/v1"></label></div><div class="config-section"><span class="config-index">02</span><div><h3>Chroma 向量库</h3><p>配置向量服务连接与知识集合。</p></div><div class="config-fields"><label>主机<input v-model="systemConfig.chroma_host" required></label><label>端口<input v-model="systemConfig.chroma_port" inputmode="numeric" required></label><label class="wide-field">集合名称<input v-model="systemConfig.chroma_collection" required></label></div></div><div class="config-section"><span class="config-index">03</span><div><h3>文件与审查参数</h3><p>存储路径使用相对路径，风险阈值范围为 0 到 1。</p></div><div class="config-fields"><label class="wide-field">上传文件存储路径<input v-model="systemConfig.upload_storage_path" required></label><label>AI 风险默认阈值<input v-model="systemConfig.ai_risk_threshold" inputmode="decimal" required></label></div></div><div class="config-submit"><button class="button button-primary" type="submit" :disabled="working==='config'">{{ working==='config'?'正在保存…':'保存系统参数' }}</button></div></form></section>
        </section>
      </main>

      <footer class="product-footer"><span>© 2026 Contract Review Assistant</span><span>AI 辅助建议不具备法律效力</span></footer>
      <transition name="modal"><div v-if="uploadModal" class="modal-backdrop" @click.self="working!=='upload' && (uploadModal=false)"><section class="modal-panel upload-modal-panel" role="dialog" aria-modal="true"><header><div><span class="section-label">New review</span><h2>上传合同</h2></div><button class="modal-close" aria-label="关闭" :disabled="working==='upload'" @click="uploadModal=false">×</button></header><div class="upload-modal-drop" :class="{selected:uploadFile}" @click="$refs.modalFile.click()" @dragover.prevent="dragActive=true" @dragleave.prevent="dragActive=false" @drop.prevent="dropFile"><input ref="modalFile" type="file" accept=".pdf,.docx" hidden @change="pickFile"><span class="upload-symbol">↑</span><strong>{{ uploadFile?.name || '选择 PDF 或 DOCX 合同' }}</strong><small>单个文件最大 20MB</small></div><label class="upload-project-label">归属项目<select v-model="uploadProject" :disabled="working==='upload'"><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.project_name }}</option></select></label><div v-if="working==='upload' || uploadProgress" class="upload-progress"><div><span>{{ uploadStage }}</span><b>{{ uploadProgress }}%</b></div><i><span :style="{width:uploadProgress+'%'}"></span></i></div><div class="modal-actions"><button class="button button-secondary" :disabled="working==='upload'" @click="uploadModal=false">取消</button><button class="button button-primary" :disabled="!uploadFile || working==='upload'" @click="upload">{{ working==='upload'?'正在处理…':'上传并解析' }}</button></div></section></div></transition>
      <transition name="modal"><div v-if="adminModal" class="modal-backdrop" @click.self="adminModal=null"><section class="modal-panel admin-modal" role="dialog" aria-modal="true"><header><div><span class="section-label">Administration</span><h2>{{ adminModal.type==='rule' ? (adminModal.mode==='create'?'新增规则':'编辑规则') : adminModal.type==='knowledge' ? (adminModal.mode==='create'?'新增知识条目':'编辑知识条目') : adminModal.type==='user' ? '新增用户账号' : '重置用户密码' }}</h2></div><button class="modal-close" aria-label="关闭" @click="adminModal=null">×</button></header><form @submit.prevent="submitAdminModal"><template v-if="adminModal.type==='rule'"><label>规则名称<input v-model="adminModal.data.rule_name" required></label><div class="modal-grid"><label>规则类型<select v-model="adminModal.data.rule_type"><option value="num">数值</option><option value="regex">正则</option><option value="keyword">关键词</option></select></label><label>风险等级<select v-model="adminModal.data.risk_level"><option>高</option><option>中</option><option>低</option></select></label></div><label>规则内容<input v-model="adminModal.data.rule_content" required></label><label>规则描述<textarea v-model="adminModal.data.description"></textarea></label></template><template v-else-if="adminModal.type==='knowledge'"><label>知识库分类<select v-model="adminModal.data.category"><option value="law">民法典法条库</option><option value="enterprise_spec">企业合同规范库</option></select></label><label>标题<input v-model="adminModal.data.title" required></label><label>内容<textarea v-model="adminModal.data.content" required></textarea></label><label>参考编号<input v-model="adminModal.data.reference_no" required></label></template><template v-else-if="adminModal.type==='user'"><div class="modal-grid"><label>用户名<input v-model="adminModal.data.username" required minlength="3" autocomplete="off"></label><label>显示名称<input v-model="adminModal.data.display_name" required></label></div><label>初始密码<input type="password" v-model="adminModal.data.password" required minlength="8" autocomplete="new-password"></label><label>用户角色<select v-model="adminModal.data.role"><option value="uploader">上传人员 uploader</option><option value="legal_reviewer">法务审核员 legal_reviewer</option><option value="admin">管理员 admin</option></select></label></template><template v-else><p class="modal-tip">为账号 <strong>{{ adminModal.data.username }}</strong> 设置新密码。</p><label>新密码<input type="password" v-model="adminModal.data.password" required minlength="8" autocomplete="new-password"></label></template><div class="modal-actions"><button type="button" class="button button-secondary" @click="adminModal=null">取消</button><button type="submit" class="button button-primary" :disabled="working==='admin-modal'">{{ working==='admin-modal'?'正在提交…':'确认保存' }}</button></div></form></section></div></transition>
      <transition name="modal"><div v-if="confirmDialog" class="modal-backdrop" @click.self="confirmDialog=null"><section class="modal-panel confirm-panel" role="alertdialog" aria-modal="true"><span class="confirm-symbol" :class="{config:confirmDialog.type==='config'}">!</span><h2>{{ confirmDialog.type==='config'?'确认保存系统参数':'确认删除' }}</h2><p>{{ confirmDialog.type==='config'?'保存后新参数将立即用于后续请求，是否继续？':'确定删除“'+confirmDialog.name+'”吗？此操作无法撤销。' }}</p><div class="modal-actions"><button class="button button-secondary" @click="confirmDialog=null">取消</button><button class="button" :class="confirmDialog.type==='config'?'button-primary':'button-danger'" :disabled="working==='delete' || working==='config'" @click="confirmAction">{{ working==='delete'?'正在删除…':working==='config'?'正在保存…':confirmDialog.type==='config'?'确认保存':'确认删除' }}</button></div></section></div></transition>
    </div>
  `
}).mount('#app');
