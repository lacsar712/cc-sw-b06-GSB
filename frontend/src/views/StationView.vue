<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api.js'
import { statusText, eventText, fmtTime } from '../status.js'

const router = useRouter()
const role = ref(localStorage.getItem('role') || '')
const jobs = ref([])
const claimers = ref([])
const history = ref([])
const err = ref('')
const busyId = ref(0)

// 筛选：领取人 / 灯种
const filterAssignee = ref('')
const filterLamp = ref('')
// 每行预选的改派目标
const targets = ref({})

let timer

const isWriter = computed(() => role.value === 'writer')

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    const q = new URLSearchParams()
    if (filterAssignee.value) q.set('assignee', filterAssignee.value)
    if (filterLamp.value.trim()) q.set('lamp', filterLamp.value.trim())
    const data = await api('/api/station?' + q.toString())
    jobs.value = data.jobs || []
    claimers.value = data.claimers || []
    history.value = data.history || []
    for (const j of jobs.value) {
      if (!(j.id in targets.value)) {
        targets.value[j.id] = nextClaimer(j.assignee)
      }
    }
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

function nextClaimer(current) {
  return (claimers.value.length ? claimers.value : ['领取员甲', '领取员乙']).find(
    (c) => c !== current,
  ) || ''
}

async function reassign(j) {
  err.value = ''
  const target = targets.value[j.id]
  if (!target || target === j.assignee) {
    err.value = '请选择不同于当前领取人的目标'
    return
  }
  busyId.value = j.id
  try {
    await api(`/api/jobs/${j.id}/reassign`, {
      method: 'POST',
      body: JSON.stringify({ assignee: target }),
    })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busyId.value = 0
  }
}

function resetFilter() {
  filterAssignee.value = ''
  filterLamp.value = ''
  refresh()
}

function goDetail(id) {
  router.push(`/jobs/${id}`)
}

onMounted(() => {
  role.value = localStorage.getItem('role') || ''
  refresh()
  timer = setInterval(refresh, 1000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="station">
    <p v-if="err" class="err">{{ err }}</p>

    <section class="filters">
      <h3>署名台 · 在途改派</h3>
      <label>
        领取人
        <select v-model="filterAssignee">
          <option value="">全部</option>
          <option v-for="c in claimers" :key="c" :value="c">{{ c }}</option>
        </select>
      </label>
      <label>
        灯种
        <input v-model="filterLamp" placeholder="如 氦灯" @keyup.enter="refresh" />
      </label>
      <button type="button" @click="refresh">筛选</button>
      <button type="button" @click="resetFilter">重置</button>
      <span class="role-hint">
        {{ isWriter ? '校准员：可改派在途单（已结案锁定）' : '巡检员：只读署名与履历，不可改派' }}
      </span>
    </section>

    <h4>已署名清单（{{ jobs.length }}）</h4>
    <table class="grid">
      <thead>
        <tr>
          <th>编号</th>
          <th>灯种</th>
          <th>领取进程</th>
          <th>领取人署名</th>
          <th>署名时刻</th>
          <th>署名/进程核对</th>
          <th v-if="isWriter">改派</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="j in jobs" :key="j.id">
          <td><a class="link" @click="goDetail(j.id)">#{{ j.id }}</a></td>
          <td>{{ j.lamp }}</td>
          <td>
            <span class="badge" :class="'st-' + j.status">{{ statusText(j.status) }}</span>
          </td>
          <td class="assignee">{{ j.assignee }}</td>
          <td>{{ fmtTime(j.claimed_at) }}</td>
          <td>
            <span class="consistency" :class="j.signature_consistent ? 'ok' : 'bad'">
              {{ j.signature_consistent ? '一致' : '不一致' }}
            </span>
          </td>
          <td v-if="isWriter" class="reassign-cell">
            <template v-if="j.status === 'processing'">
              <select v-model="targets[j.id]">
                <option v-for="c in claimers" :key="c" :value="c" :disabled="c === j.assignee">
                  {{ c }}
                </option>
              </select>
              <button
                type="button"
                :disabled="busyId === j.id || targets[j.id] === j.assignee"
                @click="reassign(j)"
              >
                {{ busyId === j.id ? '提交中…' : '改派' }}
              </button>
            </template>
            <span v-else class="locked">已结案 · 不可改派</span>
          </td>
        </tr>
        <tr v-if="!jobs.length">
          <td :colspan="isWriter ? 7 : 6" class="empty">没有匹配的已署名任务</td>
        </tr>
      </tbody>
    </table>

    <h4>改派履历（最近 {{ history.length }} 条）</h4>
    <table class="grid">
      <thead>
        <tr>
          <th>编号</th>
          <th>事件</th>
          <th>原领取人</th>
          <th>新领取人</th>
          <th>操作人</th>
          <th>时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="e in history" :key="e.id">
          <td><a class="link" @click="goDetail(e.job_id)">#{{ e.job_id }}</a></td>
          <td>
            <span class="ev" :class="'ev-' + e.kind">{{ eventText(e.kind) }}</span>
          </td>
          <td>{{ e.from_assignee || '—' }}</td>
          <td>{{ e.to_assignee || '—' }}</td>
          <td>{{ e.actor || '—' }}</td>
          <td>{{ fmtTime(e.created_at) }}</td>
        </tr>
        <tr v-if="!history.length">
          <td colspan="6" class="empty">暂无履历</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.filters {
  margin: 12px 0;
  padding: 12px;
  border: 1px solid #ccc;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.filters h3 {
  width: 100%;
  margin: 0 0 4px;
}
.role-hint {
  color: #666;
  font-size: 13px;
}
h4 {
  margin: 18px 0 8px;
}
.grid {
  border-collapse: collapse;
  width: 100%;
  font-size: 14px;
}
.grid th,
.grid td {
  border: 1px solid #c8d0d8;
  padding: 6px 8px;
  text-align: left;
}
.grid th {
  background: #eef2f6;
}
.link {
  color: #1558b0;
  cursor: pointer;
  text-decoration: underline;
}
.assignee {
  font-weight: 600;
}
.empty {
  text-align: center;
  color: #888;
}
.badge {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.st-pending {
  background: #eee;
  color: #555;
}
.st-processing {
  background: #fff3cd;
  color: #8a6100;
}
.st-done {
  background: #d7ecd9;
  color: #1d6b32;
}
.consistency {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.consistency.ok {
  background: #d7ecd9;
  color: #1d6b32;
}
.consistency.bad {
  background: #f8d7da;
  color: #842029;
}
.ev {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.ev-claim {
  background: #e2e8f0;
  color: #334155;
}
.ev-reassign {
  background: #ffe3b3;
  color: #8a5200;
}
.ev-complete {
  background: #d7ecd9;
  color: #1d6b32;
}
.locked {
  color: #999;
  font-size: 12px;
}
.err {
  color: #b00020;
}
</style>
