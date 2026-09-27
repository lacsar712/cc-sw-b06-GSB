<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const role = ref(localStorage.getItem('role') || '')
const claimNames = ref([])
const inflight = ref([])
const signed = ref([])
const history = ref([])
const err = ref('')
const filterName = ref('')
const filterLamp = ref('')
const pick = ref({})
let timer

const STATUS_LABEL = { pending: '待处理', claiming: '领取中', done: '已结案' }
const KIND_LABEL = { claim: '领取', reassign: '改派' }

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    const params = new URLSearchParams()
    if (filterName.value) params.set('claim_name', filterName.value)
    if (filterLamp.value) params.set('lamp', filterLamp.value)
    const qs = params.toString()
    const data = await api('/api/signature-desk' + (qs ? '?' + qs : ''))
    claimNames.value = data.claim_names
    inflight.value = data.inflight
    signed.value = data.signed
    history.value = data.history
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function reassign(job) {
  err.value = ''
  const name = pick.value[job.id]
  if (!name) {
    err.value = '请先选择要改派的领取名'
    return
  }
  try {
    await api(`/api/jobs/${job.id}/reassign`, {
      method: 'POST',
      body: JSON.stringify({ claim_name: name }),
    })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

const consistentCount = computed(() => signed.value.filter((j) => j.consistent).length)
const inconsistentCount = computed(() => signed.value.length - consistentCount.value)

onMounted(() => {
  role.value = localStorage.getItem('role') || ''
  refresh()
  timer = setInterval(refresh, 1000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <h2>署名台</h2>
    <section class="box note">
      <h3>在途改派说明</h3>
      <p>
        领取进程把新单切入「领取中」时落下领取名，结案后署名保留。
        校准员可把在途单改派另一领取名并记入履历；已结案单不可改派。巡检员只读。
      </p>
    </section>

    <p v-if="err" style="color:#b00020">{{ err }}</p>

    <section class="box">
      <h3>筛选与核对</h3>
      <label>
        领取人
        <select v-model="filterName">
          <option value="">全部</option>
          <option v-for="n in claimNames" :key="n" :value="n">{{ n }}</option>
        </select>
      </label>
      <label>
        灯种
        <input v-model="filterLamp" placeholder="按灯种核对,如 氦灯" />
      </label>
      <p class="hint">
        按当前筛选核对署名与领取进程:已署名 {{ signed.length }} 单,
        一致 {{ consistentCount }} 单,不一致 {{ inconsistentCount }} 单。
      </p>
    </section>

    <section class="box">
      <h3>在途单(可改派)</h3>
      <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr>
            <th>编号</th><th>灯种</th><th>状态</th><th>领取名</th>
            <th v-if="role === 'writer'">改派</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="j in inflight" :key="j.id">
            <td>{{ j.id }}</td>
            <td>{{ j.lamp }}</td>
            <td>{{ STATUS_LABEL[j.status] || j.status }}</td>
            <td>{{ j.claim_name || '待领取' }}</td>
            <td v-if="role === 'writer'">
              <select v-model="pick[j.id]">
                <option value="" disabled>选择领取名</option>
                <option v-for="n in claimNames" :key="n" :value="n">{{ n }}</option>
              </select>
              <button type="button" @click="reassign(j)">改派</button>
            </td>
          </tr>
          <tr v-if="!inflight.length">
            <td :colspan="role === 'writer' ? 5 : 4" style="text-align:center;">暂无在途单</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="box">
      <h3>已署名清单</h3>
      <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr>
            <th>编号</th><th>灯种</th><th>状态</th><th>结论</th>
            <th>署名(领取名)</th><th>进程应署</th><th>核对</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="j in signed" :key="j.id">
            <td>{{ j.id }}</td>
            <td>{{ j.lamp }}</td>
            <td>{{ STATUS_LABEL[j.status] || j.status }}</td>
            <td>{{ j.verdict }}</td>
            <td>{{ j.claim_name }}</td>
            <td>{{ j.expected_claim_name }}</td>
            <td :style="{ color: j.consistent ? '#0a7a2f' : '#b00020' }">
              {{ j.consistent ? '一致' : '不一致' }}
            </td>
          </tr>
          <tr v-if="!signed.length">
            <td colspan="7" style="text-align:center;">暂无已署名单</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="box">
      <h3>改派履历</h3>
      <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr>
            <th>时间(UTC)</th><th>单号</th><th>灯种</th><th>类型</th>
            <th>原领取名</th><th>新领取名</th><th>操作人</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in history" :key="h.id">
            <td>{{ h.created_at }}</td>
            <td>{{ h.job_id }}</td>
            <td>{{ h.lamp }}</td>
            <td>{{ KIND_LABEL[h.kind] || h.kind }}</td>
            <td>{{ h.from_name || '—' }}</td>
            <td>{{ h.to_name }}</td>
            <td>{{ h.changed_by }}</td>
          </tr>
          <tr v-if="!history.length">
            <td colspan="7" style="text-align:center;">暂无履历</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.box {
  margin: 16px 0;
  padding: 12px;
  border: 1px solid #ccc;
}
.note {
  background: #f4f8fb;
}
label {
  display: inline-block;
  margin-right: 12px;
}
.hint {
  color: #666;
  font-size: 13px;
}
</style>
