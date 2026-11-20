# Funky Koval Wrew Sobie --- mechanika gry

> Dokument opisuje uzgodnione założenia rozgrywki oraz ograniczenia
> techniczne wersji na Atari 8-bit.\
> Priorytetem jest prosta, przewidywalna mechanika, możliwa do wykonania
> na standardowym Atari 800XL / 65XE z 64 KB RAM.

## 1. Założenia projektu

Gra jest przygodową grą akcji z eksploracją pomieszczeń, elementami
skradania, kluczami, zamkniętymi drzwiami i przeciwnikami.

Projektujemy ją z myślą o najprostszym standardowym Atari 800XL / 65XE:

-   procesor MOS 6502,
-   64 KB RAM,
-   standardowy układ ANTIC/GTIA/POKEY,
-   bez rozszerzeń pamięci,
-   bez VBXE,
-   bez kartridża i dodatkowego sprzętu.

Nie zakładamy możliwości wykorzystania zasobów dostępnych wyłącznie na
rozszerzonych konfiguracjach Atari.

**Główna zasada projektowa:** mechanika i poziomy mają być interesujące
dzięki rozmieszczeniu pomieszczeń, przeszkód, drzwi i przeciwników, a
nie dzięki skomplikowanej fizyce, rozbudowanej sztucznej inteligencji
czy dużej liczbie obiektów.

## 2. Struktura świata

### 2.1. Warstwy świata (Layers)

Świat gry składa się z kilku niezależnych warstw. Przykładowo mogą
istnieć trzy warstwy, ale ich ostateczna liczba nie jest jeszcze
ustalona.

Każda warstwa posiada własną mapę pomieszczeń. Warstwy są odrębnymi
obszarami świata, a nie kolejnymi piętrami tego samego budynku.

Przejście pomiędzy warstwami odbywa się przez drzwi.

### 2.2. Pomieszczenia (Rooms)

-   Każde pomieszczenie ma identyczne, z góry ustalone wymiary.
-   Pomieszczenia są rozmieszczone na siatce, np. 4 kolumny × 5 wierszy.
-   Nie wszystkie pola siatki muszą zawierać pomieszczenie.
-   Każde pomieszczenie może mieć własny układ przejść, platform,
    drabin, przeciwników i przedmiotów.
-   Poziomy powinny być projektowane z użyciem niewielkiego zestawu
    powtarzalnych elementów.

Pomieszczenia nie muszą być połączone ze wszystkimi sąsiadującymi polami
siatki. Połączenia są określane jawnie.

### 2.3. Przejścia między pomieszczeniami

Kiedy Koval wychodzi poza krawędź pomieszczenia, gra ładuje kolejne
pomieszczenie i umieszcza postać przy przeciwległej krawędzi:

  Wyjście z bieżącego pomieszczenia   Wejście do następnego
  ----------------------------------- -----------------------
  Prawo                               Lewa krawędź
  Lewo                                Prawa krawędź
  Góra                                Dolna krawędź
  Dół                                 Górna krawędź

W miarę możliwości pozycja na osi prostopadłej do kierunku przejścia
jest zachowywana. Przykładowo przy przejściu w prawo Koval pojawia się
po lewej stronie nowego pomieszczenia na zbliżonej wysokości.

Nie istnieje obowiązek automatycznego łączenia sąsiednich pól siatki.
Przejścia mogą być zablokowane, nieobecne lub --- jeśli projekt poziomu
tego wymaga --- jednokierunkowe.

### 2.4. Piętra w pomieszczeniu (Floors)

Jedno pomieszczenie może zawierać kilka poziomów, pomiędzy którymi Koval
przemieszcza się za pomocą prostych elementów:

-   drabin,
-   lin,
-   wind.

Piętra są częścią jednego pomieszczenia. Nie należy ich mylić z
warstwami świata.

Mechanika przemieszczania się między piętrami powinna być prosta i
oparta na wyraźnie oznaczonych punktach wejścia/wyjścia. Nie zakładamy
realistycznej fizyki wspinania, bezwładności ani skomplikowanych
kolizji.

### 2.5. Drzwi i przejścia między warstwami

Drzwi mogą znajdować się w dowolnym pomieszczeniu i na dowolnym piętrze.

Drzwi mogą prowadzić do dowolnego pomieszczenia w dowolnej warstwie.
Pozycja pomieszczenia docelowego nie musi odpowiadać pozycji
pomieszczenia źródłowego na siatce.

Drzwi mogą być: - otwarte, - zamknięte, - zamknięte na klucz.

Szczegółowe zasady typów kluczy i ich zużywania wymagają jeszcze
ustalenia. Nie należy zakładać, że klucz jest jednorazowy albo że
istnieje kilka kolorów kluczy, dopóki nie zostanie to zdecydowane.

## 3. Koval --- poruszanie się

Koval porusza się po pomieszczeniach i pomiędzy ich piętrami.

Sterowanie i animacje powinny być ograniczone do niezbędnego zestawu
stanów, np.:

-   stanie,
-   ruch w lewo,
-   ruch w prawo,
-   kucanie w lewo,
-   kucanie w prawo,
-   skok w lewo,
-   skok w prawo,
-   wspinanie,
-   strzelanie.

Nie zakładamy rozbudowanego modelu fizyki. Ruch powinien być oparty na
prostych współrzędnych i sprawdzaniu kolizji z otoczeniem.

Kierunek, w którym zwrócony jest Koval, ma znaczenie dla strzelania.

## 4. Broń i amunicja

### 4.1. Kierunek strzału

Koval może strzelać wyłącznie w kierunku, w którym jest aktualnie
zwrócony:

-   w lewo,
-   w prawo.

Nie przewiduje się strzelania w górę ani w dół.

### 4.2. Amunicja

-   Amunicja jest ograniczona.
-   Można ją znajdować w pomieszczeniach jako przedmioty do zebrania.
-   Maksymalny zapas wynosi **99 nabojów**.
-   Licznik amunicji ma zakres od 0 do 99.
-   Zebranie amunicji przy stanie 99 nie zwiększa zapasu.
-   Oddanie strzału zużywa jeden nabój.
-   Przy stanie 0 Koval nie może strzelać.

Do przechowywania licznika wystarczy jedna zmienna 8-bitowa (`BYTE`).

Początkowa ilość amunicji oraz wielkość znajdowanych zapasów nie zostały
jeszcze ustalone.

### 4.3. Pociski

-   W danym momencie może istnieć tylko **jeden aktywny pocisk Kovala**.
-   Kolejny strzał jest możliwy dopiero po zakończeniu ruchu poprzedniego pocisku, np. po trafieniu lub zniknięciu pocisku.
-   Pocisk porusza się poziomo w kierunku strzału.
-   Pocisk nie powinien przechodzić przez zamknięte drzwi ani ściany.
-   Pocisk nie opuszcza aktualnego pomieszczenia.

Szczegółowe parametry prędkości, zasięgu i grafiki pocisku zostaną
dobrane podczas implementacji.

### 4.4. Ograniczenie liczby pocisków

Ograniczenie do jednego aktywnego pocisku jest celowe. Upraszcza: -
obsługę obiektu pocisku, - wykrywanie kolizji, - aktualizację pozycji, -
zarządzanie stanem strzelania, - wykorzystanie pamięci i zasobów
graficznych.

Nie należy dodawać wielu jednocześnie aktywnych pocisków bez ponownej
analizy kosztów i korzyści.

## 5. Przeciwnicy

W pomieszczeniach występują przeciwnicy, których Koval musi unikać.
Walka jest możliwa, ale ograniczona zapasem amunicji.

### 5.1. Wytrzymałość przeciwników

Każdy przeciwnik ma parametr `HP`, określający liczbę trafień
potrzebnych do jego zniszczenia.

-   Trafienie zmniejsza `HP` przeciwnika o 1.
-   Po osiągnięciu `HP = 0` przeciwnik zostaje usunięty z pomieszczenia.
-   Przeciwnicy mogą mieć różną wytrzymałość.
-   Niektórzy przeciwnicy giną po jednym strzale, inni wymagają kilku
    trafień.

Przykładowe wartości do wykorzystania przy projektowaniu:

  Klasa przeciwnika          Przykładowe HP
  ------------------------ ----------------
  Lekki przeciwnik                        1
  Standardowy przeciwnik                  2
  Ciężki przeciwnik                       4

To przykładowa skala, a nie zamknięta lista typów przeciwników.

### 5.2. Zachowanie po zniszczeniu

Zniszczony przeciwnik po prostu znika.

-   Nie pozostawia amunicji.
-   Nie pozostawia kluczy.
-   Nie pozostawia energii ani innych bonusów.

Przedmioty do zebrania są rozmieszczane niezależnie od przeciwników.

### 5.3. Sztuczna inteligencja

Zachowanie przeciwników powinno być możliwie proste i przewidywalne.
Preferowane są niewielkie automaty stanów, np.:

-   patrolowanie ustalonego odcinka,
-   ruch pomiędzy dwoma punktami,
-   pozostawanie w miejscu i pilnowanie obszaru,
-   prosta reakcja na obecność Kovala.

Nie zakłada się zaawansowanego pathfindingu, planowania trasy, nawigacji
po całej mapie ani skomplikowanej koordynacji wielu przeciwników.

Konkretne typy przeciwników, ich zachowania i reakcje na wykrycie Kovala
pozostają do ustalenia.

## 6. Kolizje i zagrożenia

Kolizje powinny być sprawdzane prostymi metodami, np. na podstawie
prostokątnych obszarów zajmowanych przez postać, pocisk i przeciwnika.

Należy ograniczyć liczbę obiektów aktywnych jednocześnie w
pomieszczeniu. Dokładny limit powinien wynikać z pomiarów wydajności i
pamięci w działającym silniku.

Szczegółowe konsekwencje kontaktu z przeciwnikiem (np. utrata energii,
życia lub powrót do punktu startowego) nie zostały jeszcze ustalone.

## 7. Przedmioty do zebrania

W pomieszczeniach mogą występować przedmioty istotne dla eksploracji, w
szczególności:

-   amunicja,
-   klucze.

Przedmioty są umieszczane w konkretnych miejscach pomieszczeń. Nie są
generowane dynamicznie.

Zasady dotyczące pozostałych przedmiotów, ich liczby i wpływu na
rozgrywkę wymagają osobnego ustalenia.

## 8. Założenia techniczne i ograniczenia Atari

### 8.1. Grafika

Założenia robocze dla widoku pomieszczenia:

-   ANTIC 5,
-   siatka 40 kolumn × 8 wierszy znaków,
-   4 dostępne kolory.

Projekt grafiki musi respektować tę ograniczoną paletę. Nie należy
zakładać dodatkowych kolorów wynikających z rozszerzeń sprzętowych ani
efektów, które nie zostały potwierdzone w docelowym trybie graficznym.

Elementy otoczenia powinny być budowane z powtarzalnych kafelków/znaków.
Zestaw znaków i grafiki powinien być współdzielony tam, gdzie to
możliwe.

### 8.2. Pamięć

Gra musi działać w standardowych 64 KB RAM. Pamięć dostępna dla gry jest
mniejsza niż nominalne 64 KB, ponieważ część przestrzeni zajmują lub
ograniczają system operacyjny Atari, pamięć ekranu, zestawy znaków, dane
sprzętowe i kod.

Z tego powodu:

-   nie należy przechowywać w RAM całego świata i wszystkich pomieszczeń
    jednocześnie;
-   należy ładować dane aktualnego pomieszczenia, a pozostałe
    przechowywać w pamięci programu lub w innym odpowiednim obszarze
    danych;
-   dane pomieszczeń powinny być zwarte i możliwie mocno współdzielić
    definicje kafelków;
-   stan obiektów należy przechowywać w postaci małych rekordów;
-   należy unikać dynamicznej alokacji pamięci;
-   należy unikać dużych, powielonych struktur danych;
-   pamięć trzeba budżetować i mierzyć na rzeczywistym obrazie programu.

Przykładowo mapa 40 × 8 komórek zapisana jako jeden bajt na komórkę
zajmuje 320 bajtów. To nie oznacza, że każda komórka musi zawierać pełną
grafikę --- może przechowywać jedynie identyfikator znaku/kafelka z
niewielkiego współdzielonego zestawu.

### 8.3. Procesor i logika gry

Kod powinien być dostosowany do 8-bitowego procesora 6502:

-   proste struktury danych,
-   małe liczniki i indeksy,
-   ograniczona liczba obiektów aktualizowanych w każdej klatce,
-   proste testy kolizji,
-   brak kosztownych obliczeń zmiennoprzecinkowych,
-   unikanie skomplikowanych algorytmów wyszukiwania tras.

Tam, gdzie to możliwe, należy stosować tablice, stałe i proste automaty
stanów zamiast rozbudowanych struktur obiektowych.

### 8.4. PMG i obiekty ruchome

Wykorzystanie Player/Missile Graphics musi być zaplanowane z
uwzględnieniem ograniczonej liczby sprzętowych obiektów i ich
szerokości.

Nie należy zakładać, że każdy przeciwnik, pocisk i element animacji
otrzyma osobny sprzętowy Player. Sposób renderowania trzeba dobrać do
liczby obiektów widocznych jednocześnie i możliwości łączenia lub
współdzielenia zasobów.

Mechanika jednego pocisku Kovala ogranicza złożoność, ale sama w sobie
nie przesądza, czy pocisk zostanie narysowany jako Missile, Player czy
element grafiki znakowej.

### 8.5. Płynność działania

Priorytetem jest stabilna animacja i responsywne sterowanie na
standardowym Atari.

Jeżeli liczba przeciwników lub obiektów zacznie obciążać procesor,
należy ograniczyć ich liczbę albo uprościć zachowanie, zamiast dodawać
skomplikowane optymalizacje i rozbudowane systemy.

## 9. Zasady projektowania pomieszczeń i poziomów

Projekt poziomów powinien być możliwy do wykonania bez dużego nakładu
pracy i bez rozbudowanych narzędzi.

Zalecenia:

1.  Używać stałych wymiarów pomieszczeń.
2.  Budować otoczenie z niewielkiego, współdzielonego zestawu kafelków.
3.  Ograniczać liczbę pięter i punktów wspinania w pojedynczym
    pomieszczeniu.
4.  Używać prostych, czytelnych tras patrolowych przeciwników.
5.  Ograniczać liczbę przeciwników i przedmiotów w jednym pomieszczeniu.
6.  Unikać mechanizmów wymagających skomplikowanej synchronizacji wielu
    obiektów.
7.  Projektować przejścia i drzwi jawnie, tak aby można było łatwo
    sprawdzić spójność mapy.
8.  Nie wymagać od gracza precyzyjnych, pikselowych manewrów jako
    podstawowego sposobu rozwiązywania zagadek.

Pomieszczenie powinno dać się opisać niewielkim zestawem danych: układ
kafelków, połączenia, piętra, obiekty, przeciwnicy i przedmioty.

## 10. Pętla rozgrywki

Podstawowa pętla rozgrywki wygląda następująco:

1.  Koval eksploruje pomieszczenia.
2.  Napotyka drzwi, przeszkody i przeciwników.
3.  Unika przeciwników lub eliminuje ich, jeśli uzna to za konieczne.
4.  Znajduje klucze i inne potrzebne przedmioty.
5.  Otwiera zablokowane przejścia.
6.  Przemieszcza się pomiędzy pomieszczeniami, piętrami i warstwami
    świata.
7.  Odkrywa kolejne obszary.

Ograniczona amunicja ma zachęcać do unikania walki, a nie do
eliminowania każdego przeciwnika napotkanego na drodze.

## 11. Decyzje jeszcze nieustalone

Poniższe kwestie nie są w tym dokumencie traktowane jako ustalone
reguły:

-   dokładna liczba warstw świata;
-   dokładny rozmiar siatki pomieszczeń;
-   początkowa ilość amunicji i wielkość znajdowanych zapasów;
-   rodzaje kluczy, ich liczba i zasady zużywania;
-   dokładna lista przeciwników i ich zachowania;
-   konsekwencje kontaktu Kovala z przeciwnikiem;
-   liczba punktów życia/energii Kovala;
-   dokładne parametry pocisku: prędkość, zasięg i czas życia;
-   maksymalna liczba przeciwników i przedmiotów w jednym pomieszczeniu;
-   sposób zapisu postępu i stanu odwiedzonych pomieszczeń.

## 12. Nadrzędne kryteria projektu

Każdą nową mechanikę należy oceniać według trzech kryteriów:

1.  **Czy wnosi istotną wartość do rozgrywki?**
2.  **Czy da się ją zaimplementować prosto na 6502 i standardowym Atari
    64 KB?**
3.  **Czy nie komplikuje nadmiernie projektowania i testowania
    pomieszczeń?**

Jeśli mechanika wymaga dużej ilości pamięci, skomplikowanej sztucznej
inteligencji, wielu aktywnych obiektów lub rozbudowanych danych poziomu,
należy ją uprościć albo odrzucić.

Celem jest gra, która jest ciekawa dzięki eksploracji, układowi świata,
ograniczonym zasobom i decyzjom gracza --- nie dzięki rozbudowaniu
systemów ponad możliwości docelowej platformy.
