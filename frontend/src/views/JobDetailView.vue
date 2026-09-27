<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'

const route = useRoute()
const router = useRouter()
const job = ref(null)
const err = ref('')
let timer

const STATUS_LABEL = { pending: '待处理', claiming: '领取中', done: '已结案' }

async function load() {
  err.value = ''
  try {
    job.value = await api(`/api/jobs/${route.params.id}`)
  } catch (e) {
    err.value = String(e.message || e)
  }
}

onMounted(() => {
  load()
  timer = setInterval(load, 1000)
})
onUnmounted(() => clearInterval(timer))
watch(() => route.params.id, load)
</script>

<template>
  <div>
    <p>
      <button type="button" @click="router.push('/')">返回总览</button>
    </p>
    <p v-if="err" style="color:#b00020">{{ err }}</p>
    <section v-if="job" style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>任务详情 #{{ job.id }}</h3>
      <p>灯种:{{ job.lamp }}</p>
      <p>标称 nm:{{ job.nominal_nm }}</p>
      <p>实测 nm:{{ job.measured_nm }}</p>
      <p>状态:{{ STATUS_LABEL[job.status] || job.status }}</p>
      <p>结论:{{ job.verdict }}</p>
      <p>理由:{{ job.reason }}</p>
      <p>领取名(署名):{{ job.claim_name || '—' }}</p>
    </section>
  </div>
</template>
