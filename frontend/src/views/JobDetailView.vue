<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'
import { statusText, eventText, fmtTime } from '../status.js'

const route = useRoute()
const router = useRouter()
const role = ref(localStorage.getItem('role') || '')
const claimers = ref([])
const job = ref(null)
const err = ref('')
const target = ref('')
const saving = ref(false)
let timer

const isWriter = computed(() => role.value === 'writer')
const canReassign = computed(() => isWriter.value && job.value && job.value.status === 'processing')

async function load() {
  err.value = ''
  try {
    job.value = await api(`/api/jobs/${route.params.id}`)
    if (!claimers.value.length) {
      try {
        const c = await api('/api/claimers')
        claimers.value = c.claimers || []
      } catch {
        claimers.value = []
      }
    }
    if ((!target.value || target.value === job.value.assignee) && claimers.value.length) {
      target.value = claimers.value.find((c) => c !== job.value.assignee) || ''
    }
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function reassign() {
  if (!target.value || !job.value || target.value === job.value.assignee) {
    err.value = '请选择不同于当前领取人的目标'
    return
  }
  err.value = ''
  saving.value = true
  try {
    await api(`/api/jobs/${job.value.id}/reassign`, {
      method: 'POST',
      body: JSON.stringify({ assignee: target.value }),
    })
    await load()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  role.value = localStorage.getItem('role') || ''
  load()
  timer = setInterval(load, 1000)
})
onUnmounted(() => clearInterval(timer))
watch(() => route.params.id, () => {
  target.value = ''
  load()
})
</script>

<template>
  <div>
    <p>
      <button type="button" @click="router.push('/')">返回总览</button>
      <button type="button" class="secondary" @click="router.push('/station')">去署名台</button>
    </p>
    <p v-if="err" style="color:#b00020">{{ err }}</p>
    <section v-if="job" class="card">
      <h3>任务详情 #{{ job.id }}</h3>
      <p>灯种：{{ job.lamp }}</p>
      <p>标称 nm：{{ job.nominal_nm }}</p>
      <p>实测 nm：{{ job.measured_nm }}</p>
      <p>
        领取进程：
        <span class="badge" :class="'st-' + job.status">{{ statusText(job.status) }}</span>
      </p>
      <p>
        领取人署名：<strong>{{ job.assignee || '（尚未领取）' }}</strong>
        <span class="ts">署名时刻 {{ fmtTime(job.claimed_at) }}</span>
      </p>
      <p>
        署名/进程核对：
        <span class="consistency" :class="job.signature_consistent ? 'ok' : 'bad'">
          {{ job.signature_consistent ? '一致' : '不一致' }}
        </span>
      </p>
      <p>结论：{{ job.verdict || '—' }}</p>
      <p>理由：{{ job.reason || '—' }}</p>

      <div v-if="isWriter" class="reassign-box">
        <template v-if="job.status === 'processing'">
          <label>
            改派给
            <select v-model="target">
              <option v-for="c in claimers" :key="c" :value="c" :disabled="c === job.assignee">
                {{ c }}
              </option>
            </select>
          </label>
          <button type="button" :disabled="saving || target === job.assignee" @click="reassign">
            {{ saving ? '提交中…' : '改派（履历留痕）' }}
          </button>
        </template>
        <p v-else-if="job.status === 'done'" class="locked">已结案，不可改派；署名保留为 {{ job.assignee }}</p>
        <p v-else class="locked">尚未领取，暂不可改派</p>
      </div>
      <p v-else class="locked">巡检员只读：可查看署名与改派履历，不可改派。</p>
    </section>

    <section v-if="job" class="card">
      <h4>署名 / 改派履历</h4>
      <ul class="timeline">
        <li v-for="e in job.events" :key="e.id">
          <span class="ev" :class="'ev-' + e.kind">{{ eventText(e.kind) }}</span>
          <span class="who">
            <template v-if="e.kind === 'reassign'">
              {{ e.from_assignee || '—' }} → {{ e.to_assignee || '—' }}
            </template>
            <template v-else>{{ e.to_assignee || '—' }}</template>
          </span>
          <span class="by" v-if="e.actor">操作人：{{ e.actor }}</span>
          <span class="time">{{ fmtTime(e.created_at) }}</span>
        </li>
        <li v-if="!job.events.length" class="empty">暂无履历</li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.card {
  margin: 16px 0;
  padding: 12px 16px;
  border: 1px solid #ccc;
}
.secondary {
  margin-left: 8px;
}
.ts {
  color: #777;
  font-size: 13px;
  margin-left: 8px;
}
.badge {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.st-pending { background: #eee; color: #555; }
.st-processing { background: #fff3cd; color: #8a6100; }
.st-done { background: #d7ecd9; color: #1d6b32; }
.consistency {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.consistency.ok { background: #d7ecd9; color: #1d6b32; }
.consistency.bad { background: #f8d7da; color: #842029; }
.reassign-box {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #bbb;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.locked {
  color: #888;
  font-size: 13px;
}
.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
}
.timeline li {
  padding: 6px 0;
  border-bottom: 1px dotted #ddd;
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 14px;
}
.ev {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.ev-claim { background: #e2e8f0; color: #334155; }
.ev-reassign { background: #ffe3b3; color: #8a5200; }
.ev-complete { background: #d7ecd9; color: #1d6b32; }
.who { font-weight: 600; }
.by { color: #555; }
.time { color: #888; margin-left: auto; font-size: 12px; }
.empty { color: #888; }
h4 { margin: 4px 0 8px; }
</style>
