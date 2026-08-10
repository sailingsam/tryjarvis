// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
	site: 'https://docs.tryjarvis.in',
	integrations: [
		starlight({
			title: 'Mantrin',
			logo: {
				src: './src/assets/logo.svg',
				replacesTitle: false,
			},
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/sailingsam/tryjarvis' },
			],
			customCss: ['./src/styles/custom.css'],
			components: {
				SiteTitle: './src/components/SiteTitle.astro',
			},
			sidebar: [
				{
					label: 'Get Started',
					items: [
						{ label: 'Introduction', slug: 'index' },
						{ label: 'Installation', slug: 'installation' },
						{ label: 'Talking to Mantrin', slug: 'talking-to-it' },
					],
				},
				{
					label: 'Integrations',
					items: [
						{ label: 'Overview', slug: 'integrations' },
						{ label: 'WhatsApp', slug: 'integrations/whatsapp' },
						{ label: 'Google Calendar', slug: 'integrations/google-calendar' },
						{ label: 'Gmail', slug: 'integrations/gmail' },
						{ label: 'Notion', slug: 'integrations/notion' },
						{ label: 'GitHub', slug: 'integrations/github' },
						{ label: 'Home Assistant', slug: 'integrations/home-assistant' },
						{ label: 'Spotify', slug: 'integrations/spotify' },
						{ label: 'Weather', slug: 'integrations/weather' },
						{ label: 'Google Maps', slug: 'integrations/google-maps' },
					],
				},
				{
					label: 'Reference',
					items: [
						{ label: 'Commands', slug: 'reference/commands' },
						{ label: 'Logs & the daemon', slug: 'reference/logs-and-daemon' },
						{ label: 'Config & data locations', slug: 'reference/data-and-config' },
					],
				},
				{
					label: 'Contributing',
					items: [{ label: 'Contributing', slug: 'contributing' }],
				},
			],
		}),
	],
});
